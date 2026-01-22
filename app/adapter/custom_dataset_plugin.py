from typing import Dict, Iterator, List
import json

# 可选导入：仅在完整版（包含evalscope）中可用
try:
    from evalscope.perf.arguments import Arguments
    from evalscope.perf.plugin.datasets.base import DatasetPluginBase
    from evalscope.perf.plugin.registry import register_dataset
    EVALSCOPE_AVAILABLE = True
except ImportError:
    EVALSCOPE_AVAILABLE = False
    # 定义占位符类，避免导入错误
    class Arguments:
        pass
    class DatasetPluginBase:
        pass
    def register_dataset(name):
        def decorator(cls):
            return cls
        return decorator


# 仅在完整版中注册和使用
if EVALSCOPE_AVAILABLE:
    @register_dataset('custom_dataset')
    class CustomDatasetPlugin(DatasetPluginBase):

        def __init__(self, query_parameters: Arguments):
            super().__init__(query_parameters)

        def build_messages(self) -> Iterator[List[Dict]]:
            for item in self.dataset_line_by_line(self.query_parameters.dataset_path):
                item = json.loads(item.strip())
                system_prompt = item.get('system', '')
                history = item.get('history', [])
                question = item.get('question', '') or item.get('user', '') or item.get('query', '')
                
                # 构建完整的消息列表
                messages = []
                
                # 添加系统提示（如果存在）
                if system_prompt:
                    messages.append({'role': 'system', 'content': system_prompt})
                
                # 添加历史对话（如果存在）
                if history:
                    for turn in history:
                        if 'user' in turn:
                            messages.append({'role': 'user', 'content': turn['user']})
                        if 'assistant' in turn:
                            messages.append({'role': 'assistant', 'content': turn['assistant']})
                        if 'tool' in turn:
                            messages.append({'role': 'tool', 'content': turn['tool']})
                
                # 添加当前问题
                if question:
                    messages.append({'role': 'user', 'content': question})
                
                # 一次性yield完整的消息列表
                yield messages
else:
    # 精简版模式：定义占位符类
    class CustomDatasetPlugin:
        def __init__(self, *args, **kwargs):
            raise ImportError("CustomDatasetPlugin requires evalscope. Please install the full version of dependencies.")
