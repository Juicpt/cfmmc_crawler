import argparse
import datetime as dt
import importlib
import json
import os
import re
from collections.abc import Sequence

from bs4 import BeautifulSoup
from requests import Session, session


class UserNamePasswordError(ValueError):
    pass


class VerificationCodeError(ValueError):
    pass


class CFMMCCrawler(object):
    # modular constants, mostly web addresses
    base_url = "https://investorservice.cfmmc.com"
    login_url = base_url + "/login.do"
    logout_url = base_url + "/logout.do"
    data_url = base_url + "/customer/setParameter.do"
    excel_daily_download_url = (
        base_url + "/customer/setupViewCustomerDetailFromCompanyWithExcel.do"
    )
    excel_monthly_download_url = (
        base_url + "/customer/setupViewCustomerMonthDetailFromCompanyWithExcel.do"
    )
    trade_date_list_url = base_url + "/script/tradeDateList.js"
    header = {
        "Connection": "keep-alive",
        "User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/72.0.3626.121 Safari/537.36",
    }
    query_type_dict = {"逐日": "day", "逐笔": "trade"}

    def __init__(
        self,
        account_no: str,
        password: str,
        output_dir: str,
        non_trading_days: Sequence[str] | None = None,
    ) -> None:
        """
        从期货保证金结算中心下载期货结算单到本地
        本地输出地址为 output_dir/account_no/日报 或 月报/逐日 或 逐笔/account_no_date.xls
        :param account_no: 账号
        :param password: 密码
        :param output_dir: 输出目录
        :param non_trading_days: 非交易日列表, 格式为 ["2025-02-23"]
        """
        self.account_no, self.password = account_no, password

        self.output_dir = output_dir
        self.non_trading_days = self._load_non_trading_days(non_trading_days)

        self._ss = None
        self.token = None
        ddddocr_module = importlib.import_module("ddddocr")
        self._ocr = ddddocr_module.DdddOcr(show_ad=False)

    @classmethod
    def _parse_trade_date_list_js(cls, js_text: str) -> Sequence[str]:
        match = re.search(r"disabledDates\s*=\s*\[(.*?)\]\s*;", js_text, re.S)
        if match is None:
            raise RuntimeError("tradeDateList.js 中未找到 disabledDates")
        return re.findall(r"'([0-9]{4}-[0-9]{2}-[0-9]{2})'", match.group(1))

    def _fetch_non_trading_days(self) -> Sequence[str]:
        response = session().get(
            self.trade_date_list_url, headers=self.header, timeout=10
        )
        response.raise_for_status()
        days = self._parse_trade_date_list_js(response.text)
        if not days:
            raise RuntimeError("tradeDateList.js 解析后为空")
        return days

    def _load_non_trading_days(
        self, fallback_non_trading_days: Sequence[str] | None
    ) -> set[dt.date]:
        day_strings: Sequence[str]
        try:
            day_strings = self._fetch_non_trading_days()
        except Exception:
            if fallback_non_trading_days is None:
                raise
            day_strings = fallback_non_trading_days
        return {dt.datetime.strptime(day, "%Y-%m-%d").date() for day in day_strings}

    def _get_session(self) -> Session:
        if self._ss is None:
            raise RuntimeError("会话未初始化, 请先登录")
        return self._ss

    def _recognize_verification_code(self, image_bytes: bytes) -> str:
        verification_code = self._ocr.classification(image_bytes).strip()
        print("验证码识别结果:", verification_code)
        if not verification_code:
            raise VerificationCodeError("验证码识别结果为空")
        return verification_code

    @staticmethod
    def _parse_form_token_and_captcha_src(
        page: str,
        page_name: str,
        require_captcha: bool,
        use_body_form: bool,
    ) -> tuple[str, str | None]:
        bs = BeautifulSoup(page, features="lxml")
        form_root = bs
        if use_body_form:
            body = bs.body
            if body is None:
                raise RuntimeError(f"{page_name}解析失败: 未找到 body")
            form_root = body
        form = form_root.form
        if form is None:
            raise RuntimeError(f"{page_name}解析失败: 未找到 form")

        token_input = form.input
        if token_input is None:
            raise RuntimeError(f"{page_name}解析失败: 未找到 token input")
        token_value = token_input.get("value")
        if not isinstance(token_value, str) or token_value == "":
            raise RuntimeError(f"{page_name}解析失败: token 无效")

        if not require_captcha:
            return token_value, None

        captcha_img = form.img
        if captcha_img is None:
            raise RuntimeError(f"{page_name}解析失败: 未找到验证码图片")
        captcha_src = captcha_img.get("src")
        if not isinstance(captcha_src, str) or captcha_src == "":
            raise RuntimeError(f"{page_name}解析失败: 验证码地址无效")
        return token_value, captcha_src

    def login(self) -> None:
        """
        登录
        """
        # get CAPTCHA
        self._ss = session()
        ss = self._get_session()
        res = ss.get(self.login_url, headers=self.header)
        token, captcha_src = self._parse_form_token_and_captcha_src(
            res.text, "登录页", require_captcha=True, use_body_form=True
        )
        if captcha_src is None:
            raise RuntimeError("登录页解析失败: 验证码地址无效")
        verification_code_url = self.base_url + captcha_src
        verification_code_image = ss.get(verification_code_url).content
        verification_code = self._recognize_verification_code(verification_code_image)
        print("验证码自动识别结果:", verification_code)

        post_data = {
            "org.apache.struts.taglib.html.TOKEN": token,
            "showSaveCookies": "",
            "userID": self.account_no,
            "password": self.password,
            "vericode": verification_code,
        }
        data_page = ss.post(
            self.login_url, data=post_data, headers=self.header, timeout=5
        )

        if "验证码错误" in data_page.text:
            raise VerificationCodeError("登录失败, 验证码错误, 请重试!")
        if "请勿在公用电脑上记录您的查询密码" in data_page.text:
            raise UserNamePasswordError("用户名密码错误!")

        print("登录成功...")
        self.token = self._get_token(data_page.text)

    def logout(self) -> None:
        """
        登出
        """
        if self.token:
            _ = self._get_session().post(self.logout_url)
            self.token = None

    def _check_args(self, query_type: str) -> None:
        if not self.token:
            raise RuntimeError("需要先登录成功才可进行查询!")

        if query_type not in self.query_type_dict.keys():
            raise ValueError("query_type 必须为 逐日 或 逐笔 !")

    def get_daily_data(self, date: dt.date, query_type: str) -> None:
        """
        下载日报数据

        :param date: 日期
        :param query_type: 逐日 或 逐笔
        :return: None
        """
        self._check_args(query_type)

        trade_date = date.strftime("%Y-%m-%d")
        path = os.path.join(self.output_dir, self.account_no, "日报", query_type)
        file_name = self.account_no + "_" + trade_date + ".xls"
        full_path = os.path.join(path, file_name)
        os.makedirs(path, exist_ok=True)

        post_data = {
            "org.apache.struts.taglib.html.TOKEN": self.token,
            "tradeDate": trade_date,
            "byType": self.query_type_dict[query_type],
        }
        data_page = self._get_session().post(
            self.data_url, data=post_data, headers=self.header, timeout=5
        )
        self.token = self._get_token(data_page.text)

        self._download_file(self.excel_daily_download_url, full_path)

    def get_monthly_data(self, month: dt.date, query_type: str) -> None:
        """
        下载月报数据

        :param month: 日期
        :param query_type: 逐日 或 逐笔
        :return: None
        """
        self._check_args(query_type)

        trade_date = month.strftime("%Y-%m")
        path = os.path.join(self.output_dir, self.account_no, "月报", query_type)
        file_name = self.account_no + "_" + trade_date + ".xls"
        full_path = os.path.join(path, file_name)
        os.makedirs(path, exist_ok=True)

        post_data = {
            "org.apache.struts.taglib.html.TOKEN": self.token,
            "tradeDate": trade_date,
            "byType": self.query_type_dict[query_type],
        }
        data_page = self._get_session().post(
            self.data_url, data=post_data, headers=self.header, timeout=5
        )
        self.token = self._get_token(data_page.text)

        self._download_file(self.excel_monthly_download_url, full_path)

    @staticmethod
    def _get_token(page: str) -> str:
        token, _ = CFMMCCrawler._parse_form_token_and_captcha_src(
            page, "页面", require_captcha=False, use_body_form=False
        )
        return token

    def _download_file(self, web_address: str, download_path: str) -> None:
        excel_response = self._get_session().get(web_address)
        with open(download_path, "wb") as fh:
            _ = fh.write(excel_response.content)
        print("下载 ", download_path, " 完成!")

    def get_trading_days(self, start_date: str, end_date: str) -> Sequence[dt.datetime]:
        """
        根据配置的非交易日筛选区间交易日

        :param start_date: 开始时间
        :param end_date: 结束时间
        :return: 期间的交易日列表
        """
        start = dt.datetime.strptime(start_date, "%Y%m%d").date()
        end = dt.datetime.strptime(end_date, "%Y%m%d").date()
        trading_days = []
        current = start
        while current <= end:
            if current.weekday() < 5 and current not in self.non_trading_days:
                trading_days.append(
                    dt.datetime.strptime(current.strftime("%Y%m%d"), "%Y%m%d")
                )
            current += dt.timedelta(days=1)
        return trading_days

    def batch_daily_download(self, start_date: str, end_date: str) -> None:
        """
        批量日报下载, 包括昨日和逐笔
        :param start_date: 开始日期
        :param end_date: 结束日期
        :return: None
        """
        all_trading_dates = self.get_trading_days(start_date, end_date)
        if not all_trading_dates:
            raise RuntimeError("给定区间内无可下载交易日")
        for date in all_trading_dates:
            for query_type in self.query_type_dict.keys():
                self.get_daily_data(date, query_type)

    def batch_monthly_download(self, start_date: str, end_date: str) -> None:
        """
        批量月报下载, 包括昨日和逐笔
        :param start_date: 开始日期
        :param end_date: 结束日期
        :return: None
        """
        query_months = self._generate_months_first_day(start_date, end_date)
        for month in query_months:
            for query_type in self.query_type_dict.keys():
                self.get_monthly_data(month, query_type)

    @staticmethod
    def _generate_months_first_day(start_date: str, end_date: str) -> Sequence[dt.date]:
        start = dt.date(int(start_date[:4]), int(start_date[4:6]), 1)
        end = dt.date(int(end_date[:4]), int(end_date[4:6]), 1)
        storage = []
        while start <= end:
            storage.append(start)
            start = dt.date(
                start.year + start.month // 12,
                (start.month + 1) % 13 + start.month // 12,
                1,
            )
        return storage


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量下载中国期货市场监控中心结算单")
    parser.add_argument(
        "--start-date",
        dest="start_date",
        help="开始日期，格式为 YYYYMMDD",
    )
    parser.add_argument(
        "--end-date",
        dest="end_date",
        help="结束日期，格式为 YYYYMMDD",
    )
    args = parser.parse_args()

    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    # integrity check
    needed_keys = [
        "accounts",
        "output_dir",
    ]
    for key in needed_keys:
        if key not in config.keys():
            raise ValueError(key + "不在config中")

    if (args.start_date is None) != (args.end_date is None):
        raise ValueError("--start-date 与 --end-date 必须同时提供")

    if args.start_date is not None and args.end_date is not None:
        start_date_obj = dt.datetime.strptime(args.start_date, "%Y%m%d")
        end_date_obj = dt.datetime.strptime(args.end_date, "%Y%m%d")
        if start_date_obj > end_date_obj:
            raise ValueError("--start-date 不能晚于 --end-date")
        start_date = args.start_date
        end_date = args.end_date
        only_today_daily = False
    else:
        today = dt.date.today().strftime("%Y%m%d")
        start_date = today
        end_date = today
        only_today_daily = True

    # let it begin
    for account in config["accounts"]:
        crawler = CFMMCCrawler(
            account["account_no"],
            account["password"],
            config["output_dir"],
            config.get("non_trading_days"),
        )
        print("正在登陆账号 ", account["account_no"])
        while crawler.token is None:
            try:
                crawler.login()
            except UserNamePasswordError as e:
                print(e)
                break
            except VerificationCodeError as e:
                print(e)

        if crawler.token:
            crawler.batch_daily_download(start_date, end_date)
            if not only_today_daily:
                crawler.batch_monthly_download(start_date, end_date)
            print("完成操作, 登出!")
            crawler.logout()
