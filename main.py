import logging
import re
import time
from datetime import datetime
from collections import defaultdict

import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


class StudentDataFetcher:
    def __init__(self):
        self.base_url = (
            "http://app.hama-univ.edu.sy/StdMark/Student/{student_id}?college=3"
        )
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    def convert_arabic_numbers(self, text):
        """Convert Arabic numerals to English numerals"""
        arabic_to_english = {
            "٠": "0",
            "١": "1",
            "٢": "2",
            "٣": "3",
            "٤": "4",
            "٥": "5",
            "٦": "6",
            "٧": "7",
            "٨": "8",
            "٩": "9",
        }

        result = text
        for arabic, english in arabic_to_english.items():
            result = result.replace(arabic, english)
        return result.strip()

    def get_status(self, mark):
        """Get pass/fail status based on mark"""
        try:
            mark_float = float(mark)
            if mark_float >= 60:
                return "✅ ناجح"
            else:
                return "❌ راسب"
        except:
            return "❓ غير معروف"

    def parse_date(self, date_str):
        """Parse date string YYYY/MM/DD to datetime object for sorting"""
        try:
            return datetime.strptime(date_str.strip(), "%Y/%m/%d")
        except:
            return None

    def fetch_student_data(self, student_id):
        """Fetch student data from the website"""
        try:
            url = self.base_url.format(student_id=student_id)
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            response.encoding = "utf-8"

            soup = BeautifulSoup(response.text, "html.parser")

            # Extract student name
            name_element = soup.find("span", class_="bottom")
            name = name_element.text.strip() if name_element else "غير معروف"

            # Extract year from last panel-heading
            panel_headings = soup.find_all(class_="panel-heading")
            year = panel_headings[-1].text.strip() if panel_headings else "غير معروف"

            # Get all tables and use the last one (current year)
            tables = soup.find_all("table", class_="table-striped")
            if not tables:
                return None

            last_table = tables[-1]

            # Extract subject data
            subjects_data = []  # List to store all subject occurrences
            rows = last_table.find_all("tr")

            for row in rows[1:]:  # Skip header row
                cells = row.find_all("td")
                if len(cells) >= 4:
                    subject_name = cells[0].text.strip()
                    semester = cells[1].text.strip()
                    mark_str = cells[2].text.strip()
                    release_date = cells[-1].text.strip()  # Last column is release date

                    if subject_name and mark_str:
                        # Convert mark to float
                        mark_clean = self.convert_arabic_numbers(mark_str)
                        try:
                            mark = float(mark_clean)
                            status = self.get_status(mark)
                            parsed_date = self.parse_date(release_date)

                            subjects_data.append(
                                {
                                    "name": subject_name,
                                    "mark": mark,
                                    "status": status,
                                    "semester": semester,
                                    "mark_display": mark_str,
                                    "release_date": release_date,
                                    "parsed_date": parsed_date,
                                }
                            )
                        except ValueError:
                            continue

            # Process duplicates: for each subject, keep oldest date but newest mark
            subject_groups = defaultdict(list)

            for subject in subjects_data:
                subject_groups[subject["name"]].append(subject)

            # For each subject group, find oldest date and newest mark
            final_subjects = []
            for subject_name, occurrences in subject_groups.items():
                # Sort by date to find oldest
                sorted_by_date = sorted(
                    occurrences, key=lambda x: x["parsed_date"] or datetime.min
                )
                oldest = sorted_by_date[0]

                # Find newest mark
                newest_mark_entry = max(occurrences, key=lambda x: x["mark"])

                # Combine: oldest date + newest mark
                final_subjects.append(
                    {
                        "name": subject_name,
                        "mark": newest_mark_entry["mark"],
                        "status": self.get_status(newest_mark_entry["mark"]),
                        "semester": oldest["semester"],
                        "mark_display": newest_mark_entry["mark_display"],
                        "release_date": oldest["release_date"],
                        "parsed_date": oldest["parsed_date"],
                    }
                )

            # Sort final subjects by release date
            final_subjects.sort(key=lambda x: x["parsed_date"] or datetime.min)

            return {
                "name": name,
                "year": year,
                "id": student_id,
                "subjects": final_subjects,
            }

        except requests.RequestException as e:
            logger.error(f"Request error: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching data: {e}")
            return None


class TelegramBot:
    def __init__(self, token):
        self.fetcher = StudentDataFetcher()

        # Get proxy from environment variable if set
        import os

        proxy_url = os.getenv("PROXY_URL")

        # Build application with or without proxy
        builder = Application.builder().token(token)
        if proxy_url:
            builder = builder.proxy(proxy_url)
        self.application = builder.build()

        self.setup_handlers()

    def setup_handlers(self):
        """Setup bot command and message handlers"""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_student_id)
        )

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        welcome_message = """👋 *مرحباً! بوت البحث عن علامات الطلاب*

📝 *كيفية الاستخدام:*
أرسل الرقم الجامعي للطالب للحصول على علاماته

⚠️ *ملاحظات:*
• الرقم يجب أن يكون مكوناً من أرقام فقط
• يتم جلب البيانات من الموقع الرسمي
• يظهر آخر تحديث للعلامات

🔍 *مثال:* `202112345`

للمساعدة أرسل `/help`"""

        await update.message.reply_text(welcome_message, parse_mode="Markdown")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_message = """📖 *مساعدة البوت*

🔧 *الأوامر المتاحة:*
• `/start` - بدء البوت
• `/help` - عرض هذه المساعدة

📝 *كيفية البحث:*
1. أرسل الرقم الجامعي (أرقام فقط)
2. انتظر حتى يتم جلب البيانات
3. ستحصل على جميع المواد والعلامات

🎯 *معلومات العرض:*
• اسم الطالب والسنة الدراسية
• جميع المواد مع العلامات
• حالة النجاح/الرسوب لكل مادة
• المعدل العام والتقييم

❓ *للمشاكل:*
• تأكد من الرقم الجامعي الصحيح
• تحقق من الاتصال بالإنترنت
• حاول مرة أخرى لاحقاً"""

        await update.message.reply_text(help_message, parse_mode="Markdown")

    def format_student_message(self, student_data):
        """Format student data for Telegram message"""
        if not student_data or not student_data["subjects"]:
            return "❌ لم يتم العثور على بيانات للطالب"

        # Calculate statistics
        total_mark = sum(s["mark"] for s in student_data["subjects"])
        avg_mark = total_mark / len(student_data["subjects"])
        passed_count = sum(1 for s in student_data["subjects"] if s["mark"] >= 60)
        failed_count = len(student_data["subjects"]) - passed_count

        # Performance rating
        if avg_mark >= 85:
            rating = "ممتاز 🏆"
        elif avg_mark >= 75:
            rating = "جيد جداً 🥈"
        elif avg_mark >= 65:
            rating = "جيد 🥉"
        else:
            rating = "مقبول ⚠️"

        # Book emojis (red, green, blue, orange) - will rotate using mod 4
        book_emojis = ["📕", "📗", "📘", "📙"]

        # Build message
        lines = []

        # Header
        lines.append(f"👤 *{student_data['name']}*")
        lines.append(f"🆔 {student_data['id']}")
        lines.append("")

        # Display subjects sorted by release date (oldest first)
        current_semester = None
        for i, subject in enumerate(student_data["subjects"]):
            # Add semester header when it changes
            semester_num = "1" if "1" in subject["semester"] else "2"
            if semester_num != current_semester:
                current_semester = semester_num
                lines.append(f"*الفصل {current_semester}*")

            # Get book emoji based on index (mod 4 rotation)
            book_emoji = book_emojis[i % 4]

            # Status: green check for pass, red cross for fail
            if subject["mark"] >= 60:
                mark_display = f"✅ {subject['mark_display']}"
            else:
                mark_display = f"❌ {subject['mark_display']}"

            lines.append(f"{book_emoji} {subject['name']}")
            lines.append(f"   {mark_display}")

            # Add separator between subjects
            lines.append("———————")

        # Summary
        lines.append("")
        lines.append(f"📊 المعدل: *{avg_mark:.1f}* · {rating}")
        lines.append(f"✓ الناجح: {passed_count}  ✗ الراسب: {failed_count}")

        return "\n".join(lines)

    async def handle_student_id(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle student ID input"""
        student_id = update.message.text.strip()

        # Validate input (digits only)
        if not student_id.isdigit():
            await update.message.reply_text(
                "❌ الرقم الجامعي يجب أن يكون مكوناً من أرقام فقط\n\n"
                "📝 *مثال:* `202112345`",
                parse_mode="Markdown",
            )
            return

        # Send typing action
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action="typing"
        )

        # Fetch student data
        await update.message.reply_text(
            "🔍 *جاري البحث عن بيانات الطالب...*", parse_mode="Markdown"
        )

        student_data = self.fetcher.fetch_student_data(student_id)

        if student_data is None:
            await update.message.reply_text(
                "❌ لم يتم العثور على الطالب\n\n"
                "🔍 *تأكد من:*"
                "• الرقم الجامعي الصحيح"
                "• وجود الطالب في النظام"
                "• الاتصال بالإنترنت",
                parse_mode="Markdown",
            )
            return

        # Format and send results
        formatted_message = self.format_student_message(student_data)

        # Split message if it's too long (Telegram limit is 4096 characters)
        if len(formatted_message) > 4000:
            # Split into parts
            parts = formatted_message.split("\n\n")
            current_message = ""

            for part in parts:
                if len(current_message + part + "\n\n") > 4000:
                    if current_message:
                        await update.message.reply_text(
                            current_message, parse_mode="Markdown"
                        )
                    current_message = part + "\n\n"
                else:
                    current_message += part + "\n\n"

            if current_message:
                await update.message.reply_text(current_message, parse_mode="Markdown")
        else:
            await update.message.reply_text(formatted_message, parse_mode="Markdown")

    def run(self):
        """Start the bot"""
        logger.info("Starting Telegram bot for student marks...")
        self.application.run_polling()


def get_bot_token():
    """Get bot token from environment or .env file"""
    import os

    # Check environment variable first
    token = os.getenv("BOT_TOKEN")

    if not token:
        # Try to read from .env file
        try:
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("BOT_TOKEN="):
                        token = line.split("=", 1)[1].strip()
                        break
        except FileNotFoundError:
            pass

    return token


def main():
    bot_token = get_bot_token()

    if not bot_token or bot_token == "YOUR_BOT_TOKEN_HERE":
        print("❌ Please set BOT_TOKEN environment variable or update .env file")
        print("📝 Get your token from @BotFather on Telegram")
        return

    # Create and run bot
    bot = TelegramBot(bot_token)
    bot.run()


if __name__ == "__main__":
    # Check dependencies
    required_packages = ["requests", "bs4", "telegram"]
    missing_packages = []

    for package in required_packages:
        try:
            if package == "bs4":
                __import__("bs4")
            else:
                __import__(package)
        except ImportError:
            missing_packages.append(package)

    if missing_packages:
        print("❌ Missing required packages:")
        for package in missing_packages:
            print(f"   • {package}")
        print("\n📦 Install with: pip install -r requirements.txt")
        exit(1)

    main()  # Run the existing main function
