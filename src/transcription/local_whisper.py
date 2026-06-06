import os
import tempfile
import threading
import time
from functools import wraps

import dotenv

from src.llm.translate import TranslateProcessor
from src.llm.kimi import KimiProcessor
from ..utils.logger import logger

dotenv.load_dotenv()

def timeout_decorator(seconds):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = [None]
            error = [None]
            completed = threading.Event()

            def target():
                try:
                    result[0] = func(*args, **kwargs)
                except Exception as e:
                    error[0] = e
                finally:
                    completed.set()

            thread = threading.Thread(target=target)
            thread.daemon = True
            thread.start()

            if completed.wait(seconds):
                if error[0] is not None:
                    raise error[0]
                return result[0]
            raise TimeoutError(f"操作超时 ({seconds}秒)")

        return wrapper
    return decorator

class LocalWhisperProcessor:
    DEFAULT_TIMEOUT = 180

    def __init__(self):
        self.model_repo = os.getenv(
            "MLX_WHISPER_MODEL",
            "mlx-community/whisper-large-v3-turbo"
        )
        try:
            import mlx_whisper
            self._mlx_whisper = mlx_whisper
            logger.info(f"mlx-whisper 已加载，使用模型: {self.model_repo}")
        except ImportError:
            raise FileNotFoundError(
                "mlx-whisper 未安装。请运行: pip install mlx-whisper"
            )

        self.timeout_seconds = self.DEFAULT_TIMEOUT
        self.translate_processor = TranslateProcessor()
        self.kimi_processor = KimiProcessor()
        self.enable_kimi_polish = os.getenv("ENABLE_KIMI_POLISH", "false").lower() == "true"

    def _save_audio_to_temp_file(self, audio_buffer):
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        try:
            audio_buffer.seek(0)
            temp_file.write(audio_buffer.read())
            temp_file.flush()
            return temp_file.name
        finally:
            temp_file.close()

    @timeout_decorator(180)
    def _call_mlx_whisper(self, wav_file):
        # initial_prompt 只给一句带标点的普通话样例（不能含指令文字，否则会产生乱码）
        result = self._mlx_whisper.transcribe(
            wav_file,
            language="zh",
            path_or_hf_repo=self.model_repo,
            initial_prompt="你好，今天天气怎么样？我觉得还不错。",
        )
        return result.get("text", "").strip()

    def process_audio(self, audio_buffer, mode="transcriptions", prompt="", archive_path=None):
        wav_file = None
        try:
            start_time = time.time()
            logger.info(f"正在使用 mlx-whisper 处理音频... (模式: {mode})")

            wav_file = self._save_audio_to_temp_file(audio_buffer)
            result = self._call_mlx_whisper(wav_file)

            logger.info(f"本地处理成功 ({mode}), 耗时: {time.time() - start_time:.1f}秒")
            logger.info(f"转录结果: {result}")

            if self.enable_kimi_polish and result:
                result = self.kimi_processor.polish_text(result)

            if mode == "translations" and result:
                logger.info("正在翻译结果...")
                result = self.translate_processor.translate(result)
                logger.info(f"翻译结果: {result}")

            return result, None

        except TimeoutError:
            error_msg = f"❌ 本地处理超时 ({self.timeout_seconds}秒)"
            logger.error(error_msg)
            return None, error_msg
        except Exception as e:
            error_msg = f"❌ {str(e)}"
            logger.error(f"本地音频处理错误: {str(e)}", exc_info=True)
            return None, error_msg
        finally:
            if wav_file and os.path.exists(wav_file):
                try:
                    os.unlink(wav_file)
                except Exception as e:
                    logger.warning(f"清理临时WAV文件失败: {e}")
            try:
                audio_buffer.close()
            except Exception:
                pass
