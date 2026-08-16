import logging
from urllib.parse import urlparse


def is_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return 

# ANSI escape codes for coloring 
class ColorFormatter(logging.Formatter): 
    grey = "\x1b[30;1m" 
    blue = "\x1b[34;1m" 
    yellow = "\x1b[33;21m" 
    red = "\x1b[31m" 
    reset = "\x1b[0m" 

    def format(self, record): 
        log_fmt = self.grey + '%(asctime)s ' + self.reset + '%(levelname)s  %(message)s' 
        if record.levelno == logging.INFO: 
            log_fmt = self.grey + '%(asctime)s ' + self.blue + '%(levelname)s' + self.reset + '  %(message)s' 
        elif record.levelno == logging.WARNING: 
            log_fmt = self.grey + '%(asctime)s ' + self.yellow + '%(levelname)s' + self.reset + '  %(message)s' 
        elif record.levelno == logging.ERROR: 
            log_fmt = self.grey + '%(asctime)s ' + self.red + '%(levelname)s' + self.reset + '  %(message)s' 
            
        formatter = logging.Formatter(log_fmt, datefmt='%Y-%m-%d %H:%M:%S') 
        return formatter.format(record) # Настройка логирования с цветами 