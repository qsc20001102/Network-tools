import logging
import os
import sys

def get_base_dir():
    """获取程序真实所在目录，兼容开发与打包"""
    if getattr(sys, 'frozen', False):   # 打包后的 exe
        return os.path.dirname(sys.executable)
    else:                               # 普通 Python 运行
        return os.path.dirname(os.path.abspath(sys.argv[0]))

def setup_logger():
    base_dir = get_base_dir()
    log_file = os.path.join(base_dir, 'app.log')  # 直接放在 main 同级目录

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

    logging.info("日志系统初始化完成，日志文件路径：%s", log_file)
    return logging.getLogger(__name__)
