#!/usr/bin/env python3
import json
import sys
import os
import pathlib
import time
from sh import gpg, duplicity  # type: ignore
import sh
from jsonargparse import ArgumentParser, ActionConfigFile, Namespace
from typing import Callable, List, Tuple
import textwrap
import regex as re

from result_reader import ResultReader, EmailSender, DummySender

import logging
import logging.handlers


logging.basicConfig(level=logging.INFO)

logFormatter = logging.Formatter(
    "%(asctime)s [%(filename)s:%(lineno)s - %(funcName)20s() ] [%(levelname)-5.5s]  %(message)s"
)

consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(logFormatter)
# logging.getLogger().addHandler(consoleHandler)
logging.getLogger().handlers[0].setFormatter(
    logFormatter
)  # reconfigure the root logger


SSH_BASED_PROTOS = ["ssh", "rsync"]


class ConfigurationIssue(Exception):
    pass


class ConfigParser:
    def __init__(self):
        self._cfg_d: Namespace
        parser = ArgumentParser(
            default_config_files=["/opt/backup.yml"],
            env_prefix="DUPBACK",
            default_env=True,
        )

        parser.add_argument(
            "--command",
            required=False,
            default="",
            choices=[
                "full",
                "backup",
                "inc",
                "verify",
                "collection-status",
                "list-current-files",
                "restore",
                "remove-older-than",
                "remove-all-but-n-full",
                "cleanup",
                "replicate",
            ],
            help="Set duplicity command e.g. full, restore, remove-all-but-n-full",
        )
        parser.add_argument(
            "--args",
            type=List[str],
            required=False,
            default=[],
            help="(Default None) Extra args to duplicity.",
        )
        parser.add_argument("--config", action=ActionConfigFile)
        parser.add_argument(
            "--title",
            type=str,
            required=False,
            default="Backup",
            help="Nice name if the Job.",
        )

        # optional overrides
        parser.add_argument(
            "--gpg.fingerprint",
            type=str,
            required=True,
            default="",
            help="Fingerprint of GPG key used to encrypt/sign backups.",
        )
        parser.add_argument(
            "--gpg.public-key-pem",
            type=str,
            required=False,
            help="Public key in pem format.",
        )
        parser.add_argument(
            "--gpg.private-key-pem",
            type=str,
            required=False,
            help="Private key in pem format (password protected).",
        )
        parser.add_argument(
            "--source.baseDir",
            type=str,
            required=False,
            default="",
            help="Base/root directory on the source filesystem. --directories are inside of this location.",
        )
        parser.add_argument(
            "--dest.baseDir",
            type=str,
            required=True,
            help="Base/root directory on the destination filesystem. --directories will go to this location.",
        )
        parser.add_argument(
            "--dest.proto", type=str, required=False, help="Protocol used to backup."
        )
        parser.add_argument(
            "--dest.user",
            type=str,
            required=False,
            help="User on the destination host to connect as.",
        )
        parser.add_argument(
            "--dest.host",
            type=str,
            required=False,
            help="The hostname or IP of the destination host.",
        )
        parser.add_argument(
            "--dest.port",
            type=int,
            required=False,
            help="Port on the destination host to connect on.",
        )
        parser.add_argument(
            "--dest.uri",
            type=str,
            required=False,
            default="",
            help="Override *connection* URI. Does not change other `dest` values.",
        )
        parser.add_argument(
            "--directories",
            type=List[str],
            required=False,
            default=[],
            help="list of directories to backup. in json syntax '[dirA, dirB]'",
        )
        parser.add_argument(
            "--all-subdirectories",
            type=bool,
            default=False,
            help="all 1st level subdirectories of `source-basedir` get separatly backuped. `directories are ignored`",
        )
        parser.add_argument(
            "--no-default-config",
            action="store_true",
            required=False,
            default=False,
            help="do not load default config values from code and files.",
        )
        parser.add_argument(
            "--do-full-after",
            required=False,
            default=0,
            help="Create a full backup after given # incrementals. It is recommend to use this with duplicity option --skip-if-no-change. Otherwise you may want to use duplicity option --full-if-older-than",
        )

        parser.add_argument(
            "--keep-n-full",
            required=False,
            default=0,
            help="Clean up with duplicity `remove-all-but-n-full` to clean up",
        )
        parser.add_argument(
            "--log-level",
            required=False,
            help="Set loglevel NOTSET, DEBUG, INFO, WARNING, ERROR, CRITICAL",
        )
        self.parser = parser

    def validate_config(self) -> bool:
        validators = [
            self._validate_gpg_settings,
            self._validate_url,
            self._validate_sourcedir,
        ]
        status = True
        msg = ""
        for validator in validators:
            val_status, val_msg = validator()
            status = status and val_status
            msg += val_msg
        if not status:
            raise ConfigurationIssue(msg)
        return True

    def _validate_gpg_settings(self) -> Tuple[bool, str]:
        if self._cfg_d.gpg.fingerprint == "":
            cp.usage()
            msg = "You MUST set `gpg.fingerprint` to a valid GPG public key. Use gpg --list-keys to see what's available.\n"
            logging.error(msg)
            return False, msg
        else:
            try:
                public_key_available = self._cfg_d.gpg.fingerprint in gpg(  # type: ignore
                    "--list-keys",
                    "--with-colons",
                    "--with-fingerprint",
                    self._cfg_d.gpg.fingerprint,
                )
            except sh.ErrorReturnCode as sh_err:
                if b"No public key" in sh_err.stderr:
                    public_key_available = False
                else:
                    raise sh_err

            if not public_key_available:
                print(
                    f"No key found with fingerprint {self._cfg_d.gpg.fingerprint}, try import"
                )
                if len(self._cfg_d.gpg.public_key_pem) > 0:
                    try:
                        gpg("--import", _in=self._cfg_d.gpg.public_key_pem)
                        gpg(
                            "--import-ownertrust",
                            _in=f"{self._cfg_d.gpg.fingerprint}:6:\n",
                        )
                        if not self._cfg_d.gpg.fingerprint in gpg(
                            "--list-keys", "--with-colon", "--with-fingerprint"
                        ):
                            msg = f"Wrong key was imported, check fingerprint.\n"
                            logging.info(gpg("--list-keys"))
                            logging.info(gpg("--export-ownertrust"))
                            return False, msg
                        print("Public Key import successful.")
                    except sh.ErrorReturnCode as sh_err:
                        msg = f"""Can't import and trust public key: 
                            Command: {sh_err.full_cmd}
                            StdOut: {sh_err.stdout}
                            StrErr: {sh_err.stderr}\n"""
                        return False, msg
                else:
                    msg = f'No public key to import set "gpg.public_key_pem". Abort.\n'
                    return False, msg

            if self._cfg_d.gpg.private_key_pem:
                try:
                    private_key_imported = self._cfg_d.gpg.fingerprint in gpg(
                        "--list-secret-keys",
                        "--with-colons",
                        "--with-fingerprint",
                        self._cfg_d.gpg.fingerprint,
                    )
                except sh.ErrorReturnCode as sh_err:
                    private_key_imported = False

                if not private_key_imported:
                    try:
                        gpg(
                            "--import",
                            "--batch",
                            "--with-colons",
                            _in=self._cfg_d.gpg.private_key_pem,
                        )
                        if not self._cfg_d.gpg.fingerprint in gpg(
                            "--list-secret-keys", "--with-colon", "--with-fingerprint"
                        ):
                            sys.stderr.write(
                                f"Wrong key was imported, check fingerprint.\n"
                            )
                            print(gpg("--list-secret-keys"))
                            if not os.getenv("PASSPHRASE"):
                                print(
                                    "If your private key is encrypted, ensure env var 'PASSPHRASE' is set and valid."
                                )
                            sys.exit(1)
                        print("Privat Key import successful.")
                    except sh.ErrorReturnCode as sh_err:
                        msg = f"""Can't import privat key: 
                            Command: {sh_err.full_cmd}
                            StdOut: {sh_err.stdout}
                            StrErr: {sh_err.stderr}\n"""
                        return False, msg
            return True, ""

    def _validate_url(self) -> Tuple[bool, str]:
        if self._cfg_d.dest.uri == "":
            self._cfg_d.dest.uri = f"{self._cfg_d.dest.proto}:/{self._cfg_d.dest.user}@{self._cfg_d.dest.host}:{self._cfg_d.dest.port}/"
        return True, ""

    def _validate_sourcedir(self) -> Tuple[bool, str]:
        if self._cfg_d.all_subdirectories:
            # replacing directories with all subdirectories of source base dir
            rootdir = f"{self._cfg_d.source.baseDir}"
            if pathlib.Path(rootdir):
                subdirs = [
                    x.name
                    for x in os.scandir(rootdir)
                    if x.is_dir() and not x.name.startswith((".", "@"))
                ]
                self._cfg_d.update(subdirs, "directories")

        if len(self._cfg_d.directories) <= 0:
            return False, "No Source directories found"
        return True, ""

    def add_sublevel_arguments(
        self, sublevel: str, parameters: Callable, required=False
    ):
        self.parser.add_argument(f"--{sublevel}", type=parameters, required=required)
        # self._cfg_d = None

    def __call__(self) -> Namespace:
        if not hasattr(self, "_cfg_d"):
            self._cfg_d = self.parser.parse_args()
            if self._cfg_d.no_default_config:
                self._cfg_d = self.parser.parse_args(defaults=False)
        self.validate_config()
        return self._cfg_d

    def usage(self):
        print(self.parser.print_help())


def get_no_of_increments(duplicityDest):
    pattern = re.compile(r"\{(?:[^{}]|(?R))*\}")
    inc_count = 0
    try:
        dup_out = duplicity(
            [
                "collection-status",
                duplicityDest,
                "--show-changes-in-set",
                "0",
                "--jsonstat",
            ]
        )
        dub_jsons = pattern.findall(dup_out)[0]
        dub_json = json.loads(dub_jsons)
        index_stat = dub_json.popitem()[1]
        inc_count = index_stat["json_stat"]["backup_meta"]["no_of_inc"]
    except Exception as e:
        logging.error(
            f"Can't get backup jsons statistics. Make sure to run duplicity with --jsonstat. Error: {e} at {duplicityDest}"
        )
    time.sleep(0.5)
    return inc_count


# precedence:
# 1. args (override all)
# 2. config file (overridden by above)
# 3. environment variables (overridden by above)
# 4. default values (overridden by above)

sender_params = EmailSender.get_params()
cp = ConfigParser()
cp.add_sublevel_arguments("email", sender_params)
try:
    config = cp()
    if config.email.server:
        email_param = EmailSender.EmailParameter(**config.email.as_dict())
        sender = EmailSender(email_param)
    else:
        sender = DummySender()
    rr = ResultReader(sender, title=config.title)

except ConfigurationIssue as ci:
    cp.usage()
    logging.error(ci)
    exit(2)

if config.log_level:
    logging.getLogger().setLevel(config.log_level)

for item in config.directories:
    duplicitySource = os.path.join(config.source.baseDir, item)
    duplicityDest = f"{config.dest.uri}{os.path.join(config.dest.baseDir, item)}"

    if not pathlib.Path(duplicitySource):
        sys.stderr.write(f"Couldn't find source {duplicitySource}. Skipping.\n")
        continue

    # Run some preps if SSH based connection
    proto = config.dest.uri.partition(":")[0]
    if proto in SSH_BASED_PROTOS:
        ssh = sh.ssh.bake(p=config.dest.port, l=config.dest.user)
        try:
            ssh(
                "-o",
                "UpdateHostKeys=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                config.dest.host,
                "mkdir",
                "-p",
                f"{duplicityDest}",
            )
        except Exception as e:
            msg = f"You must setup and test SSH ahead of time. See below for errors:\n{e}\n"
            logging.error(msg)
            rr.add_error(msg)
            rr.parse_and_send()
            sys.exit(1)

    if config.do_full_after > 0 and config.command in ["inc", "backup", ""]:
        if get_no_of_increments(duplicityDest) >= config.do_full_after:
            config.command = "full"

    duplicity_args = []
    skip_dest = skip_source = False
    if "full" == config.command:
        duplicity_args.append(config.command)
    elif "restore" == config.command or "verify" in config.command:
        duplicityDest, duplicitySource = duplicitySource, duplicityDest
        duplicity_args.append(config.command)
    elif any(
        [
            x in config.command
            for x in ["collection-status", "remove", "cleanup", "list-current-files"]
        ]
    ):
        skip_source = True
        duplicity_args.append(config.command)
    else:
        duplicity_args.append("backup")
    if config.args:
        if type(config.args) == list:  # no nested lists
            duplicity_args.extend(config.args)  # no nested lists
        else:
            duplicity_args.append(config.args)
    if not skip_source:
        duplicity_args.append(duplicitySource)
    if not skip_dest:
        duplicity_args.append(duplicityDest)

    prettyArgs = " ".join(duplicity_args)
    out = f"Running: duplicity --encrypt-key {config.gpg.fingerprint} {prettyArgs}\n"
    logging.info(out)

    try:
        duplicity_sh = duplicity.bake(encrypt_key=config.gpg.fingerprint)
        for line in duplicity_sh(duplicity_args, _iter=True):
            rr.add_json(line)
            logging.info(line.strip())
        if config.keep_n_full > 0 and config.command in ["inc", "backup", "full"]:
            cleanup_out = duplicity_sh(
                [
                    "remove-all-but-n-full",
                    str(config.keep_n_full),
                    "--force",
                    duplicityDest,
                ]
            )
            if not "No old backup sets found, nothing deleted" in cleanup_out:
                cleanup_out = textwrap.indent(cleanup_out, "." * 9 + " ")
                msg = f"Clean up: {duplicityDest}\n{cleanup_out}"
                logging.info(msg)
                rr.add_footer(msg)

    except sh.ErrorReturnCode as sh_err:
        rr.add_error(
            f"""ERROR exitcode: {sh_err.exit_code}
                     ============== 
                     {sh_err.stderr.decode()}
                     ============== """
        )
        rr.parse_and_send()
        print(f"ERROR exitcode: {sh_err.stderr.decode()}")
        raise sh_err
rr.parse_and_send()
