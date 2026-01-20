from flask import current_app
from app import db
from app.models import ChatSession, ChatMessage, AIModel
from app.services import model_service # To get decrypted API keys and model details
import openai # Import the OpenAI library
import traceback # For detailed error logging
from openai import APIConnectionError, RateLimitError, AuthenticationError, APIStatusError
import json # 用于序列化模型配置
import requests # For custom API calls
from app.utils import get_beijing_time

def create_chat_session(user_id, session_name=None):
    """创建一个新的对话会话。"""
    if not session_name:
        session_name = get_beijing_time().strftime('%Y-%m-%d %H:%M:%S')
    
    session = ChatSession(user_id=user_id, session_name=session_name)
    db.session.add(session)
    try:
        db.session.commit()
        return session
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"创建聊天会话失败: {e}")
        return None

def get_chat_session_by_id(session_id, user_id):
    """按ID获取用户的聊天会话。"""
    return ChatSession.query.filter_by(id=session_id, user_id=user_id).first()

def get_user_chat_sessions(user_id):
    """获取用户的所有聊天会话，按更新时间降序排列。"""
    return ChatSession.query.filter_by(user_id=user_id).order_by(ChatSession.updated_at.desc()).all()

def delete_chat_session(session):
    """删除一个聊天会话及其所有消息。"""
    if not session:
        return False
    try:
        # ChatMessage has cascade delete from ChatSession, so messages will be deleted too.
        db.session.delete(session)
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"删除聊天会话 {session.id} 失败: {e}")
        return False

def add_message_to_session(session_id, model_id, role, content, settings_snapshot=None):
    """向会话中添加一条消息。"""
    session = ChatSession.query.get(session_id)
    if not session:
        current_app.logger.error(f"向会话 {session_id} 添加消息失败: 会话不存在")
        return None

    message = ChatMessage(
        session_id=session_id,
        model_id=model_id, # Can be None if it's a user message before model selection, or system message for UI
        role=role, # 'user', 'assistant', 'system' (for prompts)
        content=content,
        settings_snapshot=settings_snapshot # Store model settings at the time of this message pair
    )
    db.session.add(message)
    
    # Update session's updated_at timestamp
    session.updated_at = get_beijing_time()
    db.session.add(session)
    
    try:
        db.session.commit()
        return message
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"向会话 {session_id} 添加消息失败: {e}")
        return None

def get_messages_for_session(session_id, limit=50):
    """获取会话的消息，按时间升序排列。"""
    return ChatMessage.query.filter_by(session_id=session_id).order_by(ChatMessage.timestamp.asc()).limit(limit).all()

def save_session_model_configs(session_id, model_configs):
    """保存会话的模型配置

    Args:
        session_id (int): 会话ID
        model_configs (list): 模型配置列表，包含每个模型的ID、名称、System Prompt和Temperature等

    Returns:
        bool: 保存成功返回True，否则返回False
    """
    try:
        session = ChatSession.query.get(session_id)
        if not session:
            current_app.logger.error(f"保存会话 {session_id} 模型配置失败: 会话不存在")
            return False
        
        # 创建全新的config_data字典，而不是修改现有的
        # 这样可以确保SQLAlchemy检测到变化
        new_config_data = {}
        if session.config_data:
            # 保留其他可能存在的配置
            new_config_data = dict(session.config_data)
        
        # 更新模型配置
        new_config_data['model_configs'] = model_configs
        
        # 将整个字典重新赋值，确保触发数据库更新
        session.config_data = new_config_data
        
        # 强制标记为已修改
        db.session.add(session)
        db.session.flush()  # 刷新会话，确保更改已应用
        db.session.commit()
        current_app.logger.info(f"会话 {session_id} 模型配置已保存")
        return True
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"保存会话 {session_id} 模型配置失败: {e}")
        return False

def get_session_model_configs(session_id):
    """获取会话的模型配置
    
    Args:
        session_id (int): 会话ID
        
    Returns:
        list: 模型配置列表，如果不存在则返回None
    """
    try:
        session = ChatSession.query.get(session_id)
        if not session:
            return None
            
        if not session.config_data:
            return None
            
        configs = session.config_data.get('model_configs')
        if configs:
            # 处理可能存在的旧格式数据（序列化的JSON字符串）
            if isinstance(configs, str):
                try:
                    parsed = json.loads(configs)
                    return parsed
                except json.JSONDecodeError:
                    return None
            return configs
        return None
    except Exception as e:
        return None

def _call_custom_api(model_id: int, messages: list, system_prompt=None, temperature=None, stream: bool = False):
    """调用自定义协议API（非OpenAI兼容）"""
    model = AIModel.query.get(model_id)
    if not model:
        def model_not_found_error_gen(): 
            yield {"error": "模型未找到", "details": f"ID 为 {model_id} 的模型不存在。", "is_final_chunk": True, "settings_snapshot": {}}
        if stream: return model_not_found_error_gen()
        else: return {"error": "模型未找到", "details": f"ID 为 {model_id} 的模型不存在。"}

    app_logger = current_app.logger
    api_key = model_service.get_decrypted_api_key(model)
    base_url = model.api_base_url.rstrip('/')
    
    model_info = {
        "id": model.id,
        "display_name": model.display_name,
        "model_identifier": model.model_identifier,
        "system_prompt": model.system_prompt or "You are a helpful assistant."
    }
    
    actual_system_prompt = system_prompt if system_prompt is not None else model_info["system_prompt"]
    actual_temperature = temperature if temperature is not None else (model.default_temperature if model.default_temperature is not None else 0.7)
    
    settings_snapshot = {
        "model_identifier": model_info["model_identifier"],
        "model_id": model_info["id"],
        "system_prompt": actual_system_prompt,
        "temperature": actual_temperature,
        "timestamp": get_beijing_time().isoformat()
    }

    # 构建请求头
    headers = {
        'Content-Type': 'application/json',
    }
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    
    # 构建请求体
    # 检查API URL是否使用dialogue格式（如备案大模型：/api/chat）
    use_dialogue_format = '/api/chat' in base_url or (base_url.endswith('/chat') and '/v1/chat/completions' not in base_url)
    
    request_body = {
        "model": model.model_identifier or "default",
        "stream": stream
    }
    
    # 处理消息格式
    # dialogue格式：只支持user和assistant角色，需要过滤system消息
    if use_dialogue_format:
        # 过滤掉system消息，只保留user和assistant
        dialogue_messages = [msg for msg in messages if msg.get('role') in ['user', 'assistant']]
        
        # 如果有system_prompt，尝试将其合并到第一条user消息中
        if actual_system_prompt and dialogue_messages and dialogue_messages[0].get('role') == 'user':
            # 将system prompt添加到第一条user消息前面
            original_content = dialogue_messages[0].get('content', '')
            dialogue_messages[0]['content'] = f"{actual_system_prompt}\n\n{original_content}"
        
        request_body["dialogue"] = dialogue_messages
        # 添加max_tokens（备案大模型需要此参数）
        request_body["max_tokens"] = 1024  # 默认值，可以根据需要调整
        # 注意：备案大模型格式不包含temperature参数
    else:
        # 使用标准messages格式（OpenAI兼容）
        request_messages = messages.copy()
        if actual_system_prompt and messages:
            system_message = {"role": "system", "content": actual_system_prompt}
            request_messages = [system_message] + messages
        elif actual_system_prompt:
            request_messages = [{"role": "system", "content": actual_system_prompt}]
        
        request_body["messages"] = request_messages
        request_body["temperature"] = actual_temperature

    if stream:
        def custom_stream_generator():
            try:
                app_logger.debug(f"向自定义API {base_url} 发送流式请求")
                response = requests.post(
                    base_url,
                    json=request_body,
                    headers=headers,
                    stream=True,
                    timeout=(10, 300)  # 10秒连接超时，300秒读取超时
                )
                response.raise_for_status()
                
                full_response_content = []
                has_yielded_any_content = False
                
                # 处理流式响应（假设是SSE格式或逐行JSON）
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    
                    # 尝试解析SSE格式：data: {...}
                    if line.startswith('data: '):
                        line = line[6:]
                    
                    # 尝试解析JSON
                    try:
                        data = json.loads(line)
                        
                        # 尝试多种响应格式
                        content = None
                        if isinstance(data, dict):
                            # 备案大模型格式：dialogue响应可能在result/content字段
                            if 'result' in data:
                                result = data['result']
                                if isinstance(result, str):
                                    content = result
                                elif isinstance(result, dict):
                                    content = result.get('content') or result.get('text') or result.get('message', '')
                            # OpenAI兼容格式
                            elif 'choices' in data and data['choices']:
                                choice = data['choices'][0]
                                if isinstance(choice, dict):
                                    delta = choice.get('delta', {})
                                    if isinstance(delta, dict):
                                        content = delta.get('content', '')
                                    elif isinstance(delta, str):
                                        content = delta
                                    else:
                                        # 如果delta不是字典也不是字符串，尝试直接从choice获取
                                        content = choice.get('content') or choice.get('text', '')
                                elif isinstance(choice, str):
                                    content = choice
                            # 简单格式
                            elif 'content' in data:
                                content = data['content'] if isinstance(data['content'], str) else str(data['content'])
                            elif 'text' in data:
                                content = data['text'] if isinstance(data['text'], str) else str(data['text'])
                            elif 'message' in data:
                                msg = data['message']
                                if isinstance(msg, dict):
                                    content = msg.get('content', '')
                                elif isinstance(msg, str):
                                    content = msg
                            # 备案大模型可能的响应格式：直接包含text字段
                            elif 'text' in data:
                                content = data['text'] if isinstance(data['text'], str) else ''
                        elif isinstance(data, str):
                            content = data
                        elif isinstance(data, list):
                            # 如果是数组，尝试获取第一个元素
                            if data and isinstance(data[0], dict):
                                first_item = data[0]
                                content = first_item.get('content') or first_item.get('text') or first_item.get('message', '')
                            elif data and isinstance(data[0], str):
                                content = data[0]
                        
                        if content and isinstance(content, str):
                            full_response_content.append(content)
                            has_yielded_any_content = True
                            yield {"content_piece": content, "settings_snapshot": settings_snapshot, "is_final_chunk": False}
                    except json.JSONDecodeError:
                        # 如果不是JSON，可能是纯文本流
                        if line.strip():
                            full_response_content.append(line)
                            has_yielded_any_content = True
                            yield {"content_piece": line, "settings_snapshot": settings_snapshot, "is_final_chunk": False}
                    except (AttributeError, TypeError) as e:
                        # 处理类型错误，记录日志但继续处理
                        app_logger.warning(f"解析响应数据时出错 (跳过此行): {e}, 原始数据: {line[:100]}")
                        continue
                
                # 发送最终响应
                final_content = "".join(full_response_content)
                yield {
                    "full_content": final_content, 
                    "settings_snapshot": settings_snapshot, 
                    "is_final_chunk": True, 
                    "empty_stream": not has_yielded_any_content
                }
            except requests.exceptions.RequestException as e:
                app_logger.error(f"自定义API调用失败 (模型: {model_info['display_name']}): {traceback.format_exc()}")
                error_msg = "API 调用失败"
                details = str(e)
                if isinstance(e, requests.exceptions.HTTPError):
                    try:
                        error_data = e.response.json()
                        details = error_data.get('error', {}).get('message', details)
                    except:
                        details = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
                yield {"error": error_msg, "details": details, "settings_snapshot": settings_snapshot, "is_final_chunk": True}
            except Exception as e:
                app_logger.error(f"自定义API调用中发生未知错误 (模型: {model_info['display_name']}): {traceback.format_exc()}")
                yield {"error": "未知错误", "details": str(e), "settings_snapshot": settings_snapshot, "is_final_chunk": True}
        
        return custom_stream_generator()
    else:
        # 非流式响应
        try:
            app_logger.debug(f"向自定义API {base_url} 发送非流式请求")
            response = requests.post(
                base_url,
                json=request_body,
                headers=headers,
                timeout=(10, 60)
            )
            response.raise_for_status()
            
            data = response.json()
            
            # 尝试多种响应格式
            content = None
            if isinstance(data, dict):
                # OpenAI兼容格式
                if 'choices' in data and data['choices']:
                    content = data['choices'][0].get('message', {}).get('content', '')
                # 简单格式
                elif 'content' in data:
                    content = data['content']
                elif 'text' in data:
                    content = data['text']
                elif 'message' in data:
                    msg = data['message']
                    if isinstance(msg, dict):
                        content = msg.get('content', '')
                    elif isinstance(msg, str):
                        content = msg
                elif 'result' in data:
                    content = data['result']
            elif isinstance(data, str):
                content = data
            
            if not content:
                content = json.dumps(data)  # 如果无法解析，返回原始JSON
            
            return {"content": content, "settings_snapshot": settings_snapshot, "has_reasoning": False}
        except requests.exceptions.RequestException as e:
            app_logger.error(f"自定义API调用失败 (模型: {model_info['display_name']}): {traceback.format_exc()}")
            error_msg = "API 调用失败"
            details = str(e)
            if isinstance(e, requests.exceptions.HTTPError):
                try:
                    error_data = e.response.json()
                    details = error_data.get('error', {}).get('message', details)
                except:
                    details = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            return {"error": error_msg, "details": details, "settings_snapshot": settings_snapshot}
        except Exception as e:
            app_logger.error(f"自定义API调用中发生未知错误 (模型: {model_info['display_name']}): {traceback.format_exc()}")
            return {"error": "未知错误", "details": str(e), "settings_snapshot": settings_snapshot}

def call_openai_compatible_api(model_id: int, messages: list, system_prompt=None, temperature=None, stream: bool = False):
    # 由于此函数在路由处理程序的app_context中被调用，所以我们可以安全地访问数据库
    # 确保在路由中调用此函数时使用了with app.app_context()
    model = AIModel.query.get(model_id)
    if not model:
        # This error happens before any stream is set up.
        def model_not_found_error_gen(): 
            yield {"error": "模型未找到", "details": f"ID 为 {model_id} 的模型不存在。", "is_final_chunk": True, "settings_snapshot": {}}
        if stream: return model_not_found_error_gen()
        else: return {"error": "模型未找到", "details": f"ID 为 {model_id} 的模型不存在。"}

    # 在函数早期（应用上下文有效时）捕获 logger 和 config 值
    app_logger = current_app.logger

    # 检查模型类型，如果是自定义类型，使用自定义API调用
    if model.model_type == 'custom':
        return _call_custom_api(model_id, messages, system_prompt, temperature, stream)
    
    # 在应用上下文中获取所有需要的数据
    api_key = model_service.get_decrypted_api_key(model)
    base_url = model.api_base_url
    
    # 保存所有模型相关数据，避免在生成器内部访问数据库
    model_info = {
        "id": model.id,
        "display_name": model.display_name,
        "model_identifier": model.model_identifier,
        "system_prompt": model.system_prompt or "You are a helpful assistant."
    }
    
    # 如果提供了自定义的system_prompt和temperature，优先使用它们
    # 否则使用模型默认值
    actual_system_prompt = system_prompt if system_prompt is not None else model_info["system_prompt"]
    actual_temperature = temperature if temperature is not None else (model.default_temperature if model.default_temperature is not None else 0.7)
    
    settings_snapshot = {
        "model_identifier": model_info["model_identifier"],
        "model_id": model_info["id"],
        "system_prompt": actual_system_prompt,
        "temperature": actual_temperature,
        # "max_tokens": model.default_max_tokens if model.default_max_tokens is not None else 1024,
        "timestamp": get_beijing_time().isoformat()
    }

    if not api_key or not base_url:
        error_msg = "API Key 未配置" if not api_key else "Base URL 未配置"
        details = f"模型 '{model_info['display_name']}' 的相关配置缺失。"
        def config_error_gen(): 
            yield {"error": error_msg, "details": details, "settings_snapshot": settings_snapshot, "is_final_chunk": True}
        if stream: return config_error_gen()
        else: return {"error": error_msg, "details": details, "settings_snapshot": settings_snapshot}

    try:
        client = openai.OpenAI(api_key=api_key, base_url=base_url)
        api_messages = [{"role": "system", "content": settings_snapshot["system_prompt"]}] + messages
        app_logger.debug(f"向模型 {model_info['display_name']} 发送 API 请求: Base URL={base_url}, Stream={stream}")
    except Exception as e_setup: # Error during client setup or message prep
        app_logger.error(f"调用API前发生错误 (模型: {model_info['display_name']}): {traceback.format_exc()}")
        def setup_error_gen(): 
            yield {"error": "API调用预处理失败", "details": str(e_setup), "settings_snapshot": settings_snapshot, "is_final_chunk": True}
        if stream: return setup_error_gen()
        else: return {"error": "API调用预处理失败", "details": str(e_setup), "settings_snapshot": settings_snapshot}

    if stream:
        def stream_generator():
            try:
                response_stream = client.chat.completions.create(
                    model=settings_snapshot["model_identifier"],
                    messages=api_messages,
                    temperature=settings_snapshot["temperature"],
                    # max_tokens=settings_snapshot["max_tokens"],
                    stream=True
                )
                full_response_content = []
                reasoning_content = []  # 存储思考过程
                has_yielded_any_content = False
                has_reasoning = False
                
                for chunk in response_stream:
                    # 检查是否有推理内容
                    if (hasattr(chunk, 'choices') and chunk.choices and 
                        hasattr(chunk.choices[0], 'delta') and chunk.choices[0].delta and
                        hasattr(chunk.choices[0].delta, 'reasoning_content') and chunk.choices[0].delta.reasoning_content):
                        reasoning_piece = chunk.choices[0].delta.reasoning_content
                        reasoning_content.append(reasoning_piece)
                        has_reasoning = True
                        # 流式发送思考过程
                        yield {"reasoning_piece": reasoning_piece, "settings_snapshot": settings_snapshot, "is_final_chunk": False}
    
                    # 处理常规内容
                    if (hasattr(chunk, 'choices') and chunk.choices and 
                        hasattr(chunk.choices[0], 'delta') and chunk.choices[0].delta and
                        hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content):
                        content_piece = chunk.choices[0].delta.content
                        full_response_content.append(content_piece)
                        has_yielded_any_content = True
                        yield {"content_piece": content_piece, "settings_snapshot": settings_snapshot, "is_final_chunk": False}
                
                # 构建最终内容，如果有推理过程，使用特殊格式
                final_content = ""
                if has_reasoning and reasoning_content:
                    reasoning_text = "".join(reasoning_content)
                    answer_text = "".join(full_response_content)
                    final_content = f"<think>{reasoning_text}</think><answer>{answer_text}</answer>"
                else:
                    final_content = "".join(full_response_content)
                
                yield {
                    "full_content": final_content, 
                    "settings_snapshot": settings_snapshot, 
                    "is_final_chunk": True, 
                    "empty_stream": not has_yielded_any_content and not has_reasoning,
                    "has_reasoning": has_reasoning
                }
            
            except (APIConnectionError, RateLimitError, AuthenticationError, APIStatusError) as e_api_stream:
                app_logger.error(f"流式API调用中发生错误 (模型: {model_info['display_name']}): {traceback.format_exc()}")
                error_type = "API 流错误"
                details_str = str(e_api_stream)
                if isinstance(e_api_stream, AuthenticationError): error_type = "API 认证失败"; details_str = "请检查API Key。"
                elif isinstance(e_api_stream, RateLimitError): error_type = "API 速率限制"
                elif isinstance(e_api_stream, APIConnectionError): error_type = "API 连接错误"
                elif isinstance(e_api_stream, APIStatusError): 
                    error_type = f"API 状态错误 ({e_api_stream.status_code})"
                    try: details_str = e_api_stream.response.json().get('error',{}).get('message', str(e_api_stream))
                    except: pass # Keep original str(e_api_stream) if parsing fails
                yield {"error": error_type, "details": details_str, "settings_snapshot": settings_snapshot, "is_final_chunk": True}
            except Exception as e_generic_stream:
                app_logger.error(f"流式API调用中发生未知错误 (模型: {model_info['display_name']}): {traceback.format_exc()}")
                yield {"error": "未知流错误", "details": str(e_generic_stream), "settings_snapshot": settings_snapshot, "is_final_chunk": True}
        return stream_generator()
    else: # Non-streaming
        try:
            completion = client.chat.completions.create(
                model=settings_snapshot["model_identifier"],
                messages=api_messages,
                temperature=settings_snapshot["temperature"],
                # max_tokens=settings_snapshot["max_tokens"],
                stream=False
            )
            
            # 检查非流式响应中的推理内容
            response_content = completion.choices[0].message.content
            reasoning_content = getattr(completion.choices[0].message, 'reasoning', None)
            
            # 如果有推理内容，使用特殊格式存储
            if reasoning_content:
                final_content = f"<think>{reasoning_content}</think><answer>{response_content}</answer>"
            else:
                final_content = response_content
                
            return {"content": final_content, "settings_snapshot": settings_snapshot, "has_reasoning": bool(reasoning_content)}
        except (APIConnectionError, RateLimitError, AuthenticationError, APIStatusError) as e_api_nonstream:
            app_logger.error(f"非流式API调用中发生错误 (模型: {model_info['display_name']}): {traceback.format_exc()}")
            error_type = "API 调用错误"
            details_str = str(e_api_nonstream)
            if isinstance(e_api_nonstream, AuthenticationError): error_type = "API 认证失败"; details_str = "请检查API Key。"
            # ... (similar detailed error typing for non-streaming) ...
            return {"error": error_type, "details": details_str, "settings_snapshot": settings_snapshot}
        except Exception as e_generic_nonstream:
            app_logger.error(f"非流式API调用中发生未知错误 (模型: {model_info['display_name']}): {traceback.format_exc()}")
            return {"error": "未知API错误", "details": str(e_generic_nonstream), "settings_snapshot": settings_snapshot} 