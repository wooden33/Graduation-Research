import json
import time
import random
import tiktoken
import litellm
import openai
from typing import Dict, List, Any, Optional, Callable
from .llm_invocation import LLMInvocation, AzureOpenAIInvocation


class ToolCallingLLMInvocation(LLMInvocation):
    """支持工具调用的LLM接口，允许LLM主动调用文件访问等工具"""
    
    def __init__(self, model: str, tools: Optional[Dict[str, Callable]] = None):
        super().__init__(model)
        self.tools = tools or {}
        self.conversation_history = []
    
    def register_tool(self, name: str, func: Callable, description: str, parameters: Dict[str, Any]):
        """注册一个工具函数"""
        self.tools[name] = {
            'function': func,
            'description': description,
            'parameters': parameters
        }
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """获取工具定义，用于传递给LLM"""
        tool_definitions = []
        for name, tool_info in self.tools.items():
            tool_def = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool_info['description'],
                    "parameters": tool_info['parameters']
                }
            }
            tool_definitions.append(tool_def)
        return tool_definitions
    
    def execute_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """执行工具调用"""
        if tool_name not in self.tools:
            raise ValueError(f"Unknown tool: {tool_name}")
        
        tool_func = self.tools[tool_name]['function']
        try:
            result = tool_func(**arguments)
            return result
        except Exception as e:
            return f"Error executing tool {tool_name}: {str(e)}"
    
    def call_model_with_tools(self, prompt: dict, max_tokens=4096, temperature=0.2, max_iterations=5):
        """
        支持工具调用的模型调用方法
        
        Args:
            prompt: 包含system和user消息的字典
            max_tokens: 最大token数
            temperature: 温度参数
            max_iterations: 最大迭代次数，防止无限循环
            
        Returns:
            tuple: (最终响应, 总prompt tokens, 总completion tokens, 工具调用历史)
        """
        if "system" not in prompt or "user" not in prompt:
            raise KeyError("The prompt dictionary must contain 'system' and 'user' keys.")
        
        # 初始化消息历史
        messages = []
        if prompt["system"]:
            messages.append({"role": "system", "content": prompt["system"]})
        messages.append({"role": "user", "content": prompt["user"]})
        
        total_prompt_tokens = 0
        total_completion_tokens = 0
        tool_call_history = []
        
        for iteration in range(max_iterations):
            # 准备调用参数
            completion_params = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            
            # 如果有工具，添加工具定义
            if self.tools:
                completion_params["tools"] = self.get_tool_definitions()
                completion_params["tool_choice"] = "auto"
            
            # 调用模型
            try:
                response = litellm.completion(**completion_params)
                
                # 处理响应
                message = response.choices[0].message
                total_prompt_tokens += response.usage.prompt_tokens
                total_completion_tokens += response.usage.completion_tokens
                
                # 添加助手响应到消息历史
                messages.append({
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": getattr(message, 'tool_calls', None)
                })
                
                # 检查是否有工具调用
                if hasattr(message, 'tool_calls') and message.tool_calls:
                    # 执行工具调用
                    for tool_call in message.tool_calls:
                        tool_name = tool_call.function.name
                        try:
                            arguments = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError:
                            arguments = {}
                        
                        # 执行工具
                        tool_result = self.execute_tool_call(tool_name, arguments)
                        
                        # 记录工具调用历史
                        tool_call_history.append({
                            'tool_name': tool_name,
                            'arguments': arguments,
                            'result': tool_result
                        })
                        
                        # 添加工具结果到消息历史
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": str(tool_result)
                        })
                    
                    # 继续下一轮对话
                    continue
                else:
                    # 没有工具调用，返回最终结果
                    return (
                        message.content,
                        total_prompt_tokens,
                        total_completion_tokens,
                        tool_call_history
                    )
                    
            except Exception as e:
                print(f"Error in tool calling iteration {iteration}: {e}")
                # 如果出错，返回当前结果
                return (
                    f"Error occurred: {str(e)}",
                    total_prompt_tokens,
                    total_completion_tokens,
                    tool_call_history
                )
        
        # 达到最大迭代次数
        return (
            "Maximum iterations reached. The model may be stuck in a tool calling loop.",
            total_prompt_tokens,
            total_completion_tokens,
            tool_call_history
        )
    
    def call_model(self, prompt: dict, max_tokens=4096, temperature=0.2):
        """
        保持与原接口兼容的方法
        如果没有注册工具，使用原始的call_model方法
        如果有工具，使用工具调用方法
        """
        if not self.tools:
            return super().call_model(prompt, max_tokens, temperature)
        else:
            result, prompt_tokens, completion_tokens, _ = self.call_model_with_tools(
                prompt, max_tokens, temperature
            )
            return (result, prompt_tokens, completion_tokens)


class ToolCallingAzureOpenAIInvocation(AzureOpenAIInvocation):
    """支持工具调用的Azure OpenAI接口"""
    
    def __init__(self, model: str, base_url: str, api_version: str, ak: str, tools: Optional[Dict[str, Callable]] = None):
        super().__init__(model, base_url, api_version, ak)
        self.tools = tools or {}
        self.conversation_history = []
    
    def register_tool(self, name: str, func: Callable, description: str, parameters: Dict[str, Any]):
        """注册一个工具函数"""
        self.tools[name] = {
            'function': func,
            'description': description,
            'parameters': parameters
        }
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """获取工具定义，用于传递给LLM"""
        tool_definitions = []
        for name, tool_info in self.tools.items():
            tool_def = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool_info['description'],
                    "parameters": tool_info['parameters']
                }
            }
            tool_definitions.append(tool_def)
        return tool_definitions
    
    def execute_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """执行工具调用"""
        if tool_name not in self.tools:
            raise ValueError(f"Unknown tool: {tool_name}")
        
        tool_func = self.tools[tool_name]['function']
        try:
            result = tool_func(**arguments)
            return result
        except Exception as e:
            return f"Error executing tool {tool_name}: {str(e)}"
    
    def call_model_with_tools(self, prompt: dict, max_tokens=4096, temperature=0.2, max_iterations=5):
        """
        支持工具调用的Azure OpenAI模型调用方法
        """
        if "system" not in prompt or "user" not in prompt:
            raise KeyError("The prompt dictionary must contain 'system' and 'user' keys.")
        
        # 初始化消息历史
        messages = []
        if prompt["system"]:
            messages.append({"role": "system", "content": prompt["system"]})
        messages.append({"role": "user", "content": prompt["user"]})
        
        total_prompt_tokens = 0
        total_completion_tokens = 0
        tool_call_history = []
        
        for iteration in range(max_iterations):
            # 准备调用参数
            completion_params = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "extra_headers": {"X-TT-LOGID": ""},
            }
            
            # 如果有工具，添加工具定义
            if self.tools:
                completion_params["tools"] = self.get_tool_definitions()
                completion_params["tool_choice"] = "auto"
            
            # 调用模型
            try:
                response = self.client.chat.completions.create(**completion_params)
                
                # 处理响应
                message = response.choices[0].message
                
                # 计算token数
                try:
                    encoding = tiktoken.encoding_for_model(self.model)
                    prompt_text = " ".join(msg["content"] for msg in messages if msg.get("content"))
                    prompt_tokens = len(encoding.encode(prompt_text))
                    completion_tokens = len(encoding.encode(message.content or ""))
                except Exception:
                    prompt_tokens = int(len(" ".join(msg["content"] for msg in messages if msg.get("content")).split()) * 1.3)
                    completion_tokens = int(len((message.content or "").split()) * 1.3)
                
                total_prompt_tokens += prompt_tokens
                total_completion_tokens += completion_tokens
                
                # 添加助手响应到消息历史
                messages.append({
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": getattr(message, 'tool_calls', None)
                })
                
                # 检查是否有工具调用
                if hasattr(message, 'tool_calls') and message.tool_calls:
                    # 执行工具调用
                    for tool_call in message.tool_calls:
                        tool_name = tool_call.function.name
                        try:
                            arguments = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError:
                            arguments = {}
                        
                        # 执行工具
                        tool_result = self.execute_tool_call(tool_name, arguments)
                        
                        # 记录工具调用历史
                        tool_call_history.append({
                            'tool_name': tool_name,
                            'arguments': arguments,
                            'result': tool_result
                        })
                        
                        # 添加工具结果到消息历史
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": str(tool_result)
                        })
                    
                    # 继续下一轮对话
                    continue
                else:
                    # 没有工具调用，返回最终结果
                    return (
                        message.content,
                        total_prompt_tokens,
                        total_completion_tokens,
                        tool_call_history
                    )
                    
            except Exception as e:
                print(f"Error in tool calling iteration {iteration}: {e}")
                # 如果出错，返回当前结果
                return (
                    f"Error occurred: {str(e)}",
                    total_prompt_tokens,
                    total_completion_tokens,
                    tool_call_history
                )
        
        # 达到最大迭代次数
        return (
            "Maximum iterations reached. The model may be stuck in a tool calling loop.",
            total_prompt_tokens,
            total_completion_tokens,
            tool_call_history
        )
    
    def call_model(self, prompt: dict, max_tokens=4096, temperature=0.2):
        """
        保持与原接口兼容的方法
        """
        if not self.tools:
            return super().call_model(prompt, max_tokens, temperature)
        else:
            result, prompt_tokens, completion_tokens, _ = self.call_model_with_tools(
                prompt, max_tokens, temperature
            )
            return (result, prompt_tokens, completion_tokens)