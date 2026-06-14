import os
import re
import tempfile
import threading
import time
from functools import wraps

import dotenv

from src.llm.translate import TranslateProcessor
from src.llm.kimi import KimiProcessor
from ..utils.logger import logger

dotenv.load_dotenv()


def _collapse_runaway_repeats(text: str) -> str:
    """兜底清理 Whisper 幻觉式重复：把同一段 1-6 字的子串连续重复 3 次以上
    折叠成一次（如"当然当然当然当然"->"当然"，"谢谢谢谢"->"谢谢"）。
    正常中文极少把同一短语连续贴 3 遍以上，所以这里很安全。"""
    if not text:
        return text
    # \1 匹配 1-6 个字符的块，后面紧跟同样的块至少 2 次（共 ≥3 次）
    collapsed = re.sub(r'(.{1,6}?)\1{2,}', r'\1', text)
    return collapsed.strip()


# 独立的 "cloud" 词（前后都不挨别的字母）才纠正为 "Claude"。
# 这样 iCloud（前面挨着 i）、Cloudflare（后面挨着 flare）等真含 cloud 的词不受影响。
_CLOUD_RE = re.compile(r'(?<![A-Za-z])cloud(?![A-Za-z])', re.IGNORECASE)


def _fix_claude_misrecognition(text: str) -> str:
    """Whisper 常把中文语流里说的英文 "Claude" 听成 "cloud"。
    用户绝大多数时候说的是 Claude，所以把孤立的 cloud 纠正回 Claude，
    但保留 iCloud / Cloudflare 这类真正含 cloud 的词。"""
    if not text:
        return text
    return _CLOUD_RE.sub("Claude", text)


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

    def warmup(self):
        """启动时预热：mlx 会为每种张量形状单独 JIT 编译 Metal 内核，
        长音频解码出很多 token → 很多形状 → 首次转录要现编译 60-80 秒。
        编译结果只缓存在进程内存里，一重启就清空，所以每次新进程的第一句都会卡。
        这里在启动阶段拿一段合成噪声跑一次完整转录（含 word_timestamps 路径），
        把这些内核提前编译好，用户真正按热键时第一句就是快的（~5 秒内）。"""
        import io
        import wave
        try:
            import numpy as np
        except ImportError:
            logger.info("跳过模型预热（缺少 numpy）")
            return

        logger.info("正在预热 mlx-whisper 模型（首次需编译 GPU 内核，约 10-20 秒，仅启动时一次）...")
        start = time.time()
        sr = 16000
        sig = (np.random.randn(sr * 3) * 800).astype(np.int16)
        buf = io.BytesIO()
        wf = wave.open(buf, "wb")
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(sig.tobytes())
        wf.close()
        buf.seek(0)
        wav_file = self._save_audio_to_temp_file(buf)
        try:
            self._call_mlx_whisper(wav_file)
            logger.info(f"模型预热完成，耗时 {time.time() - start:.1f}秒，之后转录会很快")
        except Exception as e:
            logger.warning(f"模型预热失败（不影响使用，仅首句会慢）: {e}")
        finally:
            if wav_file and os.path.exists(wav_file):
                try:
                    os.unlink(wav_file)
                except Exception:
                    pass

    @timeout_decorator(180)
    def _call_mlx_whisper(self, wav_file):
        # initial_prompt 只给一句带标点的普通话样例（不能含指令文字，否则会产生乱码）
        # 抗幻觉参数（结尾静音段常被模型反复吐"当然当然当然"/"谢谢谢谢"）：
        #   - condition_on_previous_text=True：保留前文语境，让标点风格在长音频的
        #     逐段(30s)窗口间传递下去；设为 False 会导致长句越往后标点越少。
        #     重复幻觉改由下面三道防线兜（不靠切断上下文）。
        #   - hallucination_silence_threshold：检测到长静音就跳过，专治尾部幻觉（需 word_timestamps）
        #   - compression_ratio_threshold：高重复文本触发温度回退重解码
        #   - _collapse_runaway_repeats：转录后兜底折叠疯狂重复，与 prompt 设置无关
        result = self._mlx_whisper.transcribe(
            wav_file,
            language="zh",
            path_or_hf_repo=self.model_repo,
            initial_prompt="你好，今天天气怎么样？我觉得还不错。我在用 Claude 写代码。",
            condition_on_previous_text=True,
            word_timestamps=True,
            hallucination_silence_threshold=2.0,
            compression_ratio_threshold=2.4,
            no_speech_threshold=0.6,
        )
        text = _collapse_runaway_repeats(result.get("text", "").strip())
        return _fix_claude_misrecognition(text)

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
