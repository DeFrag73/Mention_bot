import logging
from colorama import Fore, Style, init

# Ініціалізуємо colorama
init()


class CustomFormatter(logging.Formatter):
    # Формати для різних рівнів логування
    FORMATS = {
        logging.DEBUG: Fore.BLUE + "%(asctime)s - %(name)s - %(levelname)s - %(message)s" + Style.RESET_ALL,
        logging.INFO: Fore.GREEN + "%(asctime)s - %(name)s - %(levelname)s - %(message)s" + Style.RESET_ALL,
        logging.WARNING: Fore.YELLOW + "%(asctime)s - %(name)s - %(levelname)s - %(message)s" + Style.RESET_ALL,
        logging.ERROR: Fore.RED + "%(asctime)s - %(name)s - %(levelname)s - %(message)s" + Style.RESET_ALL,
        "DEFAULT": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    }

    def format(self, record):
        # Застосувати відповідний формат
        log_fmt = self.FORMATS.get(record.levelno, self.FORMATS["DEFAULT"])
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


# Налаштування логування
handler = logging.StreamHandler()
handler.setFormatter(CustomFormatter())
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(handler)
