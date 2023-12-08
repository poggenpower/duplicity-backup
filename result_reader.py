from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pprint import pprint as print
import smtplib
import ssl
from typing import Callable
import regex as re
import json
from prettytable import PrettyTable


@dataclass
class BackupStat:
    source: str
    errors: int = -1
    deltaentries: int = -1
    no_of_inc: int = -1


class Sender(ABC):
    @abstractmethod
    def send(self, report_list: list[BackupStat], *args, **kwargs) -> bool:
        """
        Send must be implemented to trigger forwaring.
        """
        return False

    @classmethod
    def get_params(cls) -> Callable:  # type: ignore
        """
        Return parameters to initializise the sender as Dataclass
        """
        pass

class DummySender(Sender):
    """
    NoOp Sender to "disbale" sending
    """
    def send(self, report_list: list[BackupStat], *args, **kwargs) -> bool:
        return False
    
    def get_params(cls) -> Callable:  # type: ignore
        @dataclass()
        class Noargs:
            pass
        return Noargs

class EmailSender(Sender):
    @dataclass
    class EmailParameter:
        server: str = "localhost"
        port: int = 587
        sender: str = "jane.doe@example.com"
        recipient: str = "jon.doe@example.com"
        user: str | None = None
        password: str | None = None

    def __init__(self, email_param: EmailParameter) -> None:
        self.server: str = email_param.server
        self.port: int = email_param.port
        self.sender = email_param.sender
        self.recipient = email_param.recipient
        self.user: str | None = email_param.user
        self.password: str | None = email_param.password

    @classmethod
    def get_params(cls) -> Callable:
        return cls.EmailParameter

    def __render_table(self, report_list: list[BackupStat]) -> PrettyTable:
        table = PrettyTable()
        table.field_names = asdict(report_list[0]).keys()
        for row in report_list:
            table.add_row(asdict(row).values())
        return table

    def _rendert_text(self, report_list: list[BackupStat], header, info=None, error=None) -> str:
        out_text = header + "\n"
        out_text += f"\n!!  {error} !!\n\n" if error else ""
        out_text += info if info else ""
        out_text += self.__render_table(report_list).get_string()
        return out_text

    def _rendert_html(self, report_list: list[BackupStat], header, info=None, error=None) -> str:
        out_text = "<h1>" + header + "</h1>\n"
        out_text += f"""
            <b style='color:red;'>{error}</b>
        """ if error else ""
        out_text += f"<p><pre>{info}</pre></p>" if info else ""
        out_text += self.__render_table(report_list).get_html_string()
        return out_text

    def send(self, report_list: list[BackupStat], status="N/A", header="", info="", error=""):
        text = self._rendert_text(report_list, f"{status} - {header}", info=info, error=error)
        html = self._rendert_html(report_list, f"{status} - {header}", info=info, error=error)
        part_text = MIMEText(text, "plain")
        part_html = MIMEText(html, "html")

        message = MIMEMultipart("alternative")
        message["Subject"] = f'{header}: {status} - {datetime.now().strftime("%Y-%m-%d")}'
        message["From"] = self.sender
        message["To"] = self.recipient
        message.attach(part_text)
        message.attach(part_html)

        context = ssl.create_default_context()
        with smtplib.SMTP(self.server, self.port) as server:
            server.ehlo()  # Can be omitted
            server.starttls(context=context)
            server.ehlo()  # Can be omitted
            if self.user and self.password:
                server.login(self.user, self.password)
            server.sendmail(self.sender, self.recipient, message.as_string())


class ResultReader:
    def __init__(self, sender, title="") -> None:
        self.title: str = title
        self.json = ""
        self.plain = ""
        self.error_msg = ""
        self.stats: list[BackupStat] = []
        self.sender: Sender = sender

    def add_json(self, input: str):
        """
        add string containging JSON blobs 
        """
        self.json += input

    def add_plain(self, input: str):
        """
        add plain text
        """
        self.plain = input

    def add_error(self, error_mgs: str):
        """
        add error message
        """
        self.error_msg = error_mgs


    def parse_and_send(self) -> None:
        """
        parse all received information and send report
        """
        pattern = re.compile(r"\{(?:[^{}]|(?R))*\}")
        json_blobs = pattern.findall(self.json)
        status = "Unknown"
        no_errors = 0
        no_delta = 0
        for result_str in json_blobs:
            result = json.loads(result_str)

            bs = BackupStat(
                result["backup_meta"].get("source", "Error no source"),
                result.get("Errors", -1),
                result.get("DeltaEntries", -1),
                result["backup_meta"].get("no_of_inc", -1),
            )
            self.stats.append(bs)
            if bs.errors > 0:
                no_errors += bs.errors
            if bs.deltaentries > 0:
                no_delta += bs.deltaentries
        if len(self.stats) >= 1:
            status = "OK" if no_errors == 0 else "ERROR"
            status = f"{status}: {no_delta} changes."
            self.sender.send(self.stats, header=self.title, status=status, info=self.plain, error=self.error_msg)
        else:
            self.sender.send(
                [BackupStat("Fatal Error")],
                "Fatal Error",
                error="no results found in duplicity output",
                info=self.json,
            )

