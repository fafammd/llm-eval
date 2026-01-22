# 可选导入：仅在完整版（包含evalscope）中可用
try:
    from evalscope.benchmarks.benchmark import BENCHMARK_MAPPINGS, BenchmarkMeta  
    from evalscope.benchmarks.data_adapter import DataAdapter  
    from evalscope.constants import OutputType  
    from evalscope.metrics import LLMJudge, Metric, mean, metric_registry
    from evalscope.utils.io_utils import jsonl_to_list
    EVALSCOPE_AVAILABLE = True
except ImportError:
    EVALSCOPE_AVAILABLE = False
    # 定义占位符类，避免导入错误
    BENCHMARK_MAPPINGS = {}
    class BenchmarkMeta:
        pass
    class DataAdapter:
        pass
    class OutputType:
        GENERATION = 'generation'
    class LLMJudge:
        pass
    class Metric:
        pass
    def mean(*args, **kwargs):
        return 0
    class metric_registry:
        @staticmethod
        def list_metrics():
            return []
        @staticmethod
        def register(*args, **kwargs):
            pass
    def jsonl_to_list(*args, **kwargs):
        return []

import json
from typing import Any, List, Union
import os.path
from collections import defaultdict
from jinja2 import Environment, FileSystemLoader
import os
import re
from app.models import Dataset
  
# 动态创建DataAdapter类  
# 注意：在精简版模式下（无evalscope），此类不可用
if EVALSCOPE_AVAILABLE:
    class CustomDatasetAdapter(DataAdapter): 
    def __init__(self, **kwargs):
        # 初始化模板环境
        template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')
        self.env = Environment(loader=FileSystemLoader(template_dir))
        
        # 注册自定义过滤器
        self.env.filters['from_json'] = lambda x: json.loads(x) if isinstance(x, str) else x
        self.env.filters['to_json'] = lambda x: json.dumps(x, ensure_ascii=False)
        self.env.filters['regex_search'] = lambda text, pattern: re.search(pattern, text).group(0) if re.search(pattern, text) else None
        
        # 加载模板
        template_content = kwargs.get('template_content')
        if not template_content:
            raise ValueError("自定义数据集必须提供 Jinja2 模板内容")
            
        try:
            # 从字符串加载模板
            self.template = self.env.from_string(template_content)
            
            # 验证必需的宏是否存在
            required_macros = ['gen_prompt', 'get_gold_answer', 'match', 'parse_pred_result', 'get_config']
            missing_macros = []
            for macro_name in required_macros:
                if not hasattr(self.template.module, macro_name):
                    missing_macros.append(macro_name)
            
            if missing_macros:
                raise ValueError(f"模板缺少以下必需的宏：{', '.join(missing_macros)}")
            
            # 从模板获取配置
            config = json.loads(self.template.module.get_config())
            self.llm_as_a_judge = config.get('llm_as_a_judge', False)
            kwargs['llm_as_a_judge'] = self.llm_as_a_judge
                
        except Exception as e:
            raise ValueError(f"加载 Jinja2 模板失败：{str(e)}")
        
        super().__init__(**kwargs)

    def load(self, dataset_name_or_path: str = None, subset_list: list = None, **kwargs) -> dict:
        dataset_name_or_path = dataset_name_or_path or self.dataset_id
        subset_list = subset_list or self.subset_list

        data_file_dict = defaultdict(str)
        data_item_dict = defaultdict(list)

        # get data file path and subset name
        if os.path.isdir(dataset_name_or_path):
            for subset_name in subset_list:
                data_file_dict[subset_name] = os.path.join(dataset_name_or_path, f'{subset_name}.jsonl')
        elif os.path.isfile(dataset_name_or_path):
            cur_subset_name = os.path.splitext(os.path.basename(dataset_name_or_path))[0]
            data_file_dict[cur_subset_name] = dataset_name_or_path
        else:
            raise ValueError(f'Invalid dataset path: {dataset_name_or_path}')

        # load data from local disk
        try:
            for subset_name, file_path in data_file_dict.items():
                data_item_dict[subset_name] = jsonl_to_list(file_path)
        except Exception as e:
            raise ValueError(f'Failed to load data from {self.dataset_id}, got error: {e}')

        data_dict = {subset_name: {'test': data_item_dict[subset_name]} for subset_name in data_file_dict.keys()}

        return data_dict

    def gen_prompt(self, input_d: dict, subset_name: str, few_shot_list: list, **kwargs):
        try:
            history = input_d.get('history', [])
            system_prompt = input_d.get('system', '')
            user_prompt = input_d.get('question', '') or input_d.get('user', '')
            
            # 使用模板生成提示词
            prompt_result = self.template.module.gen_prompt(
                system_prompt=system_prompt,
                history=history,
                user_prompt=user_prompt
            )
            
            # 解析模板返回的 JSON 字符串
            prompt_dict = json.loads(prompt_result)
            
            return self.gen_prompt_data(
                system_prompt=prompt_dict['system_prompt'],
                prompt=prompt_dict['user_prompt']
            )
        except Exception as e:
            raise ValueError(f"生成提示词失败：{str(e)}")

    def get_gold_answer(self, input_d: dict) -> str:
        try:
            # 使用模板获取标准答案
            return self.template.module.get_gold_answer(input_d=input_d)
        except Exception as e:
            raise ValueError(f"获取标准答案失败：{str(e)}")

    def match(self, gold: str, pred: str) -> dict:
        try:
            # 使用模板比较结果
            result = self.template.module.match(gold=gold, pred=pred)
            return json.loads(result)
        except Exception as e:
            raise ValueError(f"比较结果失败：{str(e)}")
        
    def llm_match(self, gold: Any, pred: Any, judge: LLMJudge, **kwargs) -> dict:
        try:
            if hasattr(self.template.module, 'llm_match'):
                # 使用模板比较结果
                raw_input = kwargs.get('raw_input', None)
                system_prompt = raw_input.get('system_prompt', '') if raw_input else ''
                history = raw_input.get('history', []) if raw_input else []
                question_keys = ['question', 'prompt', 'query', 'user']
                question = next((raw_input.get(key) for key in question_keys if raw_input and raw_input.get(key)), '')
                config = json.loads(self.template.module.get_config())
                judge_system_prompt = config.get('judge_system_prompt', '')
                judge_prompt_template = config.get('judge_prompt', '')
                
                # 动态检测模板中使用的占位符
                format_params = {}
                if '{question}' in judge_prompt_template:
                    format_params['question'] = question or ''
                if '{gold}' in judge_prompt_template:
                    format_params['gold'] = gold
                if '{pred}' in judge_prompt_template:
                    format_params['pred'] = pred
                if '{system_prompt}' in judge_prompt_template:
                    format_params['system_prompt'] = system_prompt or ''
                if '{history}' in judge_prompt_template:
                    format_params['history'] = '\n'.join(history) if history else ''
                
                judge_prompt = judge_prompt_template.format(**format_params)
                judge_response = judge(judge_prompt, judge_system_prompt)
                result = self.template.module.llm_match(judge_response)
                return json.loads(result)
            else:
                return super().llm_match(gold, pred, judge, **kwargs)
        except Exception as e:
            raise ValueError(f"比较结果失败：{str(e)}")

    def parse_pred_result(self, result: str, raw_input_d: dict = None, eval_type: str = 'checkpoint') -> str:
        try:
            # 使用模板解析预测结果
            return self.template.module.parse_pred_result(result=result)
        except Exception as e:
            raise ValueError(f"解析预测结果失败：{str(e)}")

    def compute_metric(self, review_res_list: Union[List[dict], List[List[dict]]], **kwargs) -> List[dict]:
        try:
            # 使用模板计算指标
            if hasattr(self.template.module, 'compute_metric'):
                result = self.template.module.compute_metric(review_res_list=review_res_list)
                return json.loads(result)
            else:
                res_dict = super().compute_dict_metric(review_res_list, **kwargs)
                return super().compute_metric(res_dict, **kwargs)
        except Exception as e:
            raise ValueError(f"计算指标失败：{str(e)}")

    def set_custom_template(self, template_name: str):
        """设置自定义模板
        
        Args:
            template_name: 模板文件名
        """
        try:
            self.template = self.env.get_template(template_name)
        except Exception as e:
            raise ValueError(f"加载模板 {template_name} 失败：{str(e)}")
else:
    # 精简版模式：定义占位符类
    class CustomDatasetAdapter:
        def __init__(self, **kwargs):
            raise ImportError("CustomDatasetAdapter requires evalscope. Please install the full version of dependencies.")

def register_custom_dataset_benchmark(dataset_id: int):
    """动态注册自定义数据集基准测试（仅在完整版中可用）
    
    Args:
        dataset_id: 数据集ID，用于生成唯一的基准测试名称
    """
    if not EVALSCOPE_AVAILABLE:
        raise ImportError("register_custom_dataset_benchmark requires evalscope. Please install the full version of dependencies.")
    
    benchmark_name = f'custom_dataset_{dataset_id}'

    metric_list = ['AverageAccuracy']

    # 获取dataset的模版信息
    dataset = Dataset.query.filter_by(id=dataset_id).first()
    if not dataset:
        raise ValueError(f"数据集不存在: {dataset_id}")
    template_content = dataset.jinja2_template
    if template_content:
        try:
            # 创建临时环境来解析配置
            temp_env = Environment()
            temp_env.filters['from_json'] = lambda x: json.loads(x) if isinstance(x, str) else x
            temp_env.filters['to_json'] = lambda x: json.dumps(x, ensure_ascii=False)
            temp_env.filters['regex_search'] = lambda text, pattern: re.search(pattern, text).group(0) if re.search(pattern, text) else None

            temp_template = temp_env.from_string(template_content)
            if hasattr(temp_template.module, 'get_config'):
                config = json.loads(temp_template.module.get_config())
                metric_list = config.get('metric_list', ['AverageAccuracy'])
        except Exception as e:
            print(f"警告：无法从模板中读取配置，使用默认 metric_list: {e}")
    
    for m in metric_list:
        if m not in metric_registry.list_metrics():
            metric_registry.register(Metric(name=m, object=mean))

    # 创建BenchmarkMeta实例
    benchmark_meta = BenchmarkMeta(
        name=benchmark_name,
        dataset_id=benchmark_name,
        data_adapter=CustomDatasetAdapter,
        model_adapter=OutputType.GENERATION,
        subset_list=['default'],
        metric_list=metric_list,
        few_shot_num=0,
        eval_split='test'
    )
    
    # 直接添加到全局注册表
    BENCHMARK_MAPPINGS[benchmark_name] = benchmark_meta
    
    return benchmark_name