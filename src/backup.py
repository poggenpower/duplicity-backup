#!/usr/bin/env python3
import collections
import json
import subprocess
import sys
import os
import pathlib
import time
from jsonargparse import ArgumentParser, ActionConfigFile, Namespace
from typing import Callable, List, Tuple
import textwrap
import regex as re

from result_reader import ResultReader, EmailSender, DummySender
from time_tracker import TimeTracker

import logging
import logging.handlers


logging.basicConfig(level=logging.DEBUG)

logFormatter = logging.Formatter(
    "%(asctime)s [%(filename)s:%(lineno)s - %(funcName)20s() ] [%(levelname)-5.5s]  %(message)s"
)

class ConsoleExcludeFileOnly(logging.Filter):
    """
    Filter to exclude log records with 'file_only' attribute set to True
    from being logged to the console.
    """
    def filter(self, record):
        return not getattr(record, "file_only", False)


consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(logFormatter)
# logging.getLogger().addHandler(consoleHandler)
logging.getLogger().handlers[0].setFormatter(
    logFormatter
)  # reconfigure the root logger


class ConfigurationIssue(Exception):
    pass


class ConfigParser:
    def __init__(self):
        self._cfg_d: Namespace
        parser = ArgumentParser(
            default_config_files=["/opt/backup.yml"],
            env_prefix="DUPBACK",
            default_env=True,
            logger=logging.getLogger()
        )

        parser.add_argument(
            "--command",
            required=False,
            default="backup",
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
        parser.add_argument("--config", action="config")
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
            "--k8s-local-storage-discovery.enabled",
            type=bool,
            default=False,
            help="discover local-storage paths from k8s PersistentVolumes and add them to `directories`. Requires access to k8s cluster (in-cluster or via kubeconfig).",
        )
        parser.add_argument(
            "--k8s-local-storage-discovery.storage-class-names",
            type=List[str],
            default=["local-storage"],
            help="List of storage class names to consider for k8s local-storage discovery. Default: ['local-storage']",
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
        parser.add_argument(
            "--logfile",
            type=str,
            required=False,
            default="",
            help="File to write logs to. Rotated every 7 days; keep 5 backup files.",
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
            gpg_cmd = [
                "gpg",
                "--list-keys",
                "--with-colons",
                "--with-fingerprint",
                self._cfg_d.gpg.fingerprint,
            ]

            try:
                # capture_output=True keeps your terminal clean
                # text=True handles the decoding automatically
                result = subprocess.run(gpg_cmd, capture_output=True, text=True, check=True)
                
                # If it didn't raise CalledProcessError, the key was found
                public_key_available = self._cfg_d.gpg.fingerprint in result.stdout

            except subprocess.CalledProcessError as err:
                # GPG returns non-zero if the key is missing
                if "No public key" in err.stderr:
                    public_key_available = False
                else:
                    # Re-raise if it's a different error (e.g., config error)
                    raise err

            if not public_key_available:
                logging.info(
                    f"No key found with fingerprint {self._cfg_d.gpg.fingerprint}, try import"
                )
                if len(self._cfg_d.gpg.public_key_pem) > 0:
                    try:
                        # Import the public key
                        subprocess.run(
                            ["gpg", "--import"],
                            input=self._cfg_d.gpg.public_key_pem,
                            text=True, capture_output=True, check=True
                        )
                        
                        # Import ownertrust (requires specific colon format)
                        subprocess.run(
                            ["gpg", "--import-ownertrust"],
                            input=f"{self._cfg_d.gpg.fingerprint}:6:\n",
                            text=True, capture_output=True, check=True
                        )

                        # Verify the fingerprint exists in the key list
                        list_keys = subprocess.run(
                            ["gpg", "--list-keys", "--with-colons", "--with-fingerprint"],
                            text=True, capture_output=True, check=True
                        )

                        if self._cfg_d.gpg.fingerprint not in list_keys.stdout:
                            msg = "Wrong key was imported, check fingerprint.\n"
                            
                            # Log diagnostics using standard subprocess calls
                            debug_keys = subprocess.run(["gpg", "--list-keys"], text=True, capture_output=True)
                            debug_trust = subprocess.run(["gpg", "--export-ownertrust"], text=True, capture_output=True)
                            
                            logging.info(debug_keys.stdout)
                            logging.info(debug_trust.stdout)
                            return False, msg
                            
                        logging.info("Public Key import successful.")

                    except subprocess.CalledProcessError as err:
                        msg = f"""Can't import and trust public key: 
                            Command: {' '.join(err.cmd)}
                            StdOut: {err.stdout}
                            StdErr: {err.stderr}\n"""
                        return False, msg
                else:
                    msg = f'No public key to import set "gpg.public_key_pem". Abort.\n'
                    return False, msg

            if self._cfg_d.gpg.private_key_pem:
                try:
                    # Search specifically for the fingerprint in secret keys
                    result = subprocess.run(
                        [
                            "gpg", 
                            "--list-secret-keys", 
                            "--with-colons", 
                            "--with-fingerprint", 
                            self._cfg_d.gpg.fingerprint
                        ],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    # If the command succeeds, check if the fingerprint is in the output
                    private_key_imported = self._cfg_d.gpg.fingerprint in result.stdout
                except (subprocess.CalledProcessError, FileNotFoundError):
                    # GPG returns non-zero if the key is not found
                    private_key_imported = False

                if not private_key_imported:
                    try:
                        # Import the private key using the PEM data as input
                        subprocess.run(
                            ["gpg", "--import", "--batch", "--with-colons"],
                            input=self._cfg_d.gpg.private_key_pem,
                            text=True,
                            capture_output=True,
                            check=True
                        )

                        # Verify the import by listing secret keys
                        list_secret = subprocess.run(
                            ["gpg", "--list-secret-keys", "--with-colons", "--with-fingerprint"],
                            text=True,
                            capture_output=True,
                            check=True
                        )

                        if self._cfg_d.gpg.fingerprint not in list_secret.stdout:
                            sys.stderr.write("Wrong key was imported, check fingerprint.\n")
                            
                            # Log diagnostics
                            debug_secret = subprocess.run(
                                ["gpg", "--list-secret-keys"], 
                                text=True, 
                                capture_output=True
                            )
                            print(debug_secret.stdout)

                            if not os.getenv("PASSPHRASE"):
                                print(
                                    "If your private key is encrypted, ensure env var 'PASSPHRASE' is set and valid."
                                )
                            sys.exit(1)
                            
                        print("Private Key import successful.")

                    except subprocess.CalledProcessError as err:
                        # Accessing the failed command, stdout, and stderr from the error object
                        msg = f"""Can't import privat key: 
                            Command: {' '.join(err.cmd)}
                            StdOut: {err.stdout}
                            StrErr: {err.stderr}\n"""
                        return False, msg
            return True, ""

    def _validate_url(self) -> Tuple[bool, str]:
        if self._cfg_d.dest.uri == "":
            self._cfg_d.dest.uri = f"{self._cfg_d.dest.proto}:/{self._cfg_d.dest.user}@{self._cfg_d.dest.host}:{self._cfg_d.dest.port}/"
        return True, ""

    def _validate_sourcedir(self) -> Tuple[bool, str]:
        node = os.getenv(
            "K8S_NODE_NAME", None
        )  # used for k8s local-storage discovery, see. README.md
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
        elif self._cfg_d.k8s_local_storage_discovery.enabled and node is not None:
            from k8s_local_storage_discovery import K8sLocalStorageDiscovery

            local_storage = K8sLocalStorageDiscovery(
                self._cfg_d.k8s_local_storage_discovery.storage_class_names
            )

            directories = local_storage.get_local_storage_dirs_for_node(node)
            source, directories = local_storage.discover_common_path(
                directories, self._cfg_d.source.baseDir
            )
            if len(directories) > 0:
                if self._cfg_d.source.baseDir == "":
                    self._cfg_d.source.baseDir = source
                self._cfg_d.update(directories, "directories")
                logging.info(f"Discovered local-storage directories: {directories}")

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
    dup_out = "No output"
    try:
        # Build the command list
        cmd = [
            "duplicity",
            "collection-status",
            duplicityDest,
            "--show-changes-in-set",
            "0",
            "--jsonstat",
        ]

        # Execute and capture output
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        dup_out = result.stdout

        # Your existing parsing logic
        match = pattern.findall(dup_out)
        if match:
            dub_jsons = match[0]
            dub_json = json.loads(dub_jsons)
            index_stat = dub_json.popitem()[1]
            inc_count = index_stat["json_stat"]["backup_meta"]["no_of_inc"]
            
    except subprocess.CalledProcessError as e:
        logging.exception(
            f"Duplicity command failed. Exit code: {e.returncode}. "
            f"Error: {e.stderr}. Output: {e.stdout}"
        )
    except Exception as e:
        logging.exception(
            f"Can't get backup jsons statistics. Error: {e} at {duplicityDest}. Output: {dup_out}"
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

# additional file logging if requested
if getattr(config, "logfile", None):
    try:
        fileHandler = logging.handlers.TimedRotatingFileHandler(
            config.logfile, when="D", interval=7, backupCount=5, encoding="utf-8"
        )
        fileHandler.setFormatter(logFormatter)
        # ensure the file handler respects the configured log level
        fileHandler.setLevel(logging.getLogger().level)
        logging.getLogger().addHandler(fileHandler)
        logging.info(f"Logging to file {config.logfile} (rotated every 7 days, keep 5 files)")
    except Exception as e:
        logging.error(f"Cannot open logfile {config.logfile}: {e}")

tracker = TimeTracker()

tracker.start("total_backup_process")
for item in config.directories:
    tracker.start(f"per_item", identifier=item)
    force_full = False
    duplicitySource = os.path.join(config.source.baseDir, item)
    duplicityDest = f"{config.dest.uri}{os.path.join(config.dest.baseDir, item)}"

    if not pathlib.Path(duplicitySource):
        sys.stderr.write(f"Couldn't find source {duplicitySource}. Skipping.\n")
        continue

    if config.do_full_after > 0 and config.command in ["inc", "backup", ""]:
        if get_no_of_increments(duplicityDest) >= config.do_full_after:
            force_full = True
            logging.info(f"Switching to full backup for {duplicitySource} -> {duplicityDest}")

    duplicity_args = []
    skip_dest = skip_source = False
    if "full" == config.command or force_full:
        duplicity_args.append("full")
    elif config.command in ["restore", "verify"]:
        duplicityDest, duplicitySource = duplicitySource, duplicityDest
        duplicity_args.append(config.command)
    elif config.command in ["collection-status", "remove", "cleanup", "list-current-files"]:
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

    cmd = ["duplicity", f"--encrypt-key", f"{config.gpg.fingerprint}"]
    cmd.extend(duplicity_args)
    prettyArgs = " ".join(cmd)
    logging.info(f"Running: {prettyArgs}")

    # Keep only the last 100 lines in memory
    recent_logs = collections.deque(maxlen=100)

    tracker.start("duplicity_process", identifier=item)
    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=128 * 1024 # 128KB buffer for high-speed I/O
    ) as proc:
        for line in proc.stdout: # type: ignore
            # 1. Send to your terminal's stdout immediately
            sys.stdout.write(line) 
            
            # 2. Process for your JSON logic
            clean_line = line.strip()
            if clean_line:
                rr.add_json(clean_line)
            recent_logs.append(clean_line) 
        proc.wait()
        logging.info(f"Last logs:\n" + "\n".join(recent_logs), extra={"file_only": True})

        if config.keep_n_full > 0 and config.command in ["inc", "backup", "full"]:
            params =  [      
                "duplicity",              
                "remove-all-but-n-full",
                str(config.keep_n_full),
                "--force",
                duplicityDest,
            ]
            cleanup_out = f"No output from: {params}"
            with subprocess.Popen(
                    params,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                ) as proc:
                cleanup_out, _ = proc.communicate()

            if proc.returncode != 0:
                logging.error(f"Clean up process failed with code {proc.returncode}\nRecent logs:\n" + "\n".join(cleanup_out))
                rr.add_error(
                    f"""CLEANUP ERROR exitcode: {proc.returncode}
                             ============== 
                             {cleanup_out}
                             ============== """
                )
            elif not "No old backup sets found, nothing deleted" in cleanup_out:
                cleanup_out = textwrap.indent(cleanup_out, "." * 9 + " ")
                msg = f"Clean up: {duplicityDest}\n{cleanup_out}"
                logging.info(msg)
                rr.add_footer(msg)
    tracker.stop("duplicity_process")

    if proc.returncode != 0:
        logging.error(f"Process failed with code {proc.returncode}\nRecent logs:\n" + "\n".join(recent_logs))
        rr.add_error(
            f"""ERROR exitcode: {proc.returncode}
                     ============== 
                     {recent_logs}
                     ============== """
        )
        rr.parse_and_send()
        raise subprocess.CalledProcessError(proc.returncode, cmd)
    tracker.stop("per_item")
tracker.stop("total_backup_process")

rr.parse_and_send()
try:
    logging.info(f"Summary of all backup runs: {json.dumps(rr.cached_results, indent=2)}")
    logging.info(f"Time tracking report: {json.dumps(tracker.report(), indent=2)}")
except json.decoder.JSONDecodeError:
    logging.exception("Can't serialize summary or time tracking report to JSON.")
    logging.error("Raw summary of all backup runs: " + str(rr.cached_results))
    logging.error("Raw time tracking report: " + str(tracker.report()))
logging.info("Backup process completed successfully.")
