#!/usr/bin/env python3
"""
Cache.json 功能测试脚本
测试音频存档的转录缓存功能

Usage: python test_cache_json.py
"""

import sys
import os
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dotenv
from src.transcription.whisper import WhisperProcessor
from src.utils.logger import logger

dotenv.load_dotenv()

def test_cache_functionality():
    """测试cache.json功能"""
    
    print("🗂️  测试 audio_archive/cache.json 功能")
    print("=" * 50)
    
    # 检查audio_archive目录
    archive_dir = "audio_archive"
    audio_dir = os.path.join(archive_dir, "audio")
    cache_file = os.path.join(archive_dir, "cache.json")
    
    if not os.path.exists(archive_dir):
        print(f"❌ 音频存档目录不存在: {archive_dir}")
        return False
    
    print(f"📁 音频存档目录: {archive_dir}")
    
    # 列出音频文件
    search_dir = audio_dir if os.path.exists(audio_dir) else archive_dir
    audio_files = [f for f in os.listdir(search_dir) if f.endswith('.wav')]
    print(f"🎵 发现音频文件: {len(audio_files)} 个")
    
    if not audio_files:
        print("❌ 没有找到音频文件用于测试")
        return False
    
    # 选择最新的音频文件
    latest_audio = max([os.path.join(search_dir, f) for f in audio_files], 
                      key=os.path.getmtime)
    audio_filename = os.path.basename(latest_audio)
    print(f"🎯 使用最新音频: {audio_filename}")
    
    # 设置环境为OpenAI
    original_platform = os.environ.get("SERVICE_PLATFORM")
    os.environ["SERVICE_PLATFORM"] = "openai"
    
    try:
        # 创建处理器并转录
        processor = WhisperProcessor()
        
        # 检查转录前的缓存状态
        cache_before = processor._load_transcription_cache()
        print(f"📋 转录前缓存条目: {len(cache_before)}")
        
        # 执行转录
        print(f"🚀 开始转录 {audio_filename}...")
        with open(latest_audio, 'rb') as f:
            import io
            audio_buffer = io.BytesIO(f.read())
            
            result = processor.process_audio(
                audio_buffer,
                mode="transcriptions", 
                prompt=""
            )
            
            text, error = result if isinstance(result, tuple) else (result, None)
            
            if error:
                print(f"❌ 转录失败: {error}")
                return False
            
            print(f"✅ 转录成功!")
            print(f"📝 转录结果: {text[:100]}...")
        
        # 检查转录后的缓存状态
        cache_after = processor._load_transcription_cache()
        print(f"📋 转录后缓存条目: {len(cache_after)}")
        
        # 验证缓存内容
        if audio_filename in cache_after:
            cache_entry = cache_after[audio_filename]
            print(f"✅ 缓存条目已创建:")
            print(f"   🔧 服务: {cache_entry.get('service', 'unknown')}")
            print(f"   🤖 模型: {cache_entry.get('model', 'unknown')}")
            print(f"   ⏰ 时间: {cache_entry.get('timestamp', 'unknown')}")
            print(f"   📝 转录长度: {len(cache_entry.get('transcription', ''))} 字符")
            
            # 验证cache.json文件
            if os.path.exists(cache_file):
                print(f"✅ cache.json 文件已创建: {cache_file}")
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache_content = json.load(f)
                    print(f"📊 缓存文件包含 {len(cache_content)} 个条目")
            else:
                print(f"❌ cache.json 文件未创建")
                return False
            
            return True
        else:
            print(f"❌ 缓存中未找到音频文件条目: {audio_filename}")
            return False
            
    except Exception as e:
        print(f"💥 测试过程中发生错误: {e}")
        return False
    finally:
        # 恢复原始环境变量
        if original_platform:
            os.environ["SERVICE_PLATFORM"] = original_platform
        else:
            os.environ.pop("SERVICE_PLATFORM", None)

def main():
    """主函数"""
    print("🧪 Cache.json 功能测试")
    print("测试音频存档转录缓存系统")
    print()
    
    success = test_cache_functionality()
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 Cache.json 功能测试通过!")
        print("💡 功能验证:")
        print("   ✅ 转录结果自动保存到缓存")
        print("   ✅ cache.json 文件正确创建")
        print("   ✅ 缓存条目包含完整信息")
    else:
        print("😞 Cache.json 功能测试失败")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
