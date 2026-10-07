"""
文件访问接口 - 为LLM提供自主查看文件的能力
"""
import os
import re
import glob
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import ast
import javalang
from .utils import read_file, get_code_language
from .logger import cogpathLogger


class FileAccessInterface:
    """
    为LLM提供文件访问能力的接口类
    支持文件浏览、搜索、内容获取等功能
    """
    
    def __init__(self, project_dir: str, allowed_extensions: List[str] = None):
        self.project_dir = Path(project_dir).resolve()
        self.logger = cogpathLogger.initialize_logger(__name__)
        
        # 默认允许的文件扩展名
        if allowed_extensions is None:
            self.allowed_extensions = ['.java', '.py', '.js', '.ts', '.cpp', '.c', '.h', '.hpp']
        else:
            self.allowed_extensions = allowed_extensions
    
    def list_directory(self, relative_path: str = "", max_depth: int = 2) -> Dict:
        """
        列出目录内容
        
        Args:
            relative_path: 相对于项目根目录的路径
            max_depth: 最大遍历深度
            
        Returns:
            包含目录结构信息的字典
        """
        try:
            target_path = self.project_dir / relative_path
            if not target_path.exists() or not target_path.is_dir():
                return {"error": f"Directory not found: {relative_path}"}
            
            result = {
                "path": str(relative_path),
                "type": "directory",
                "contents": []
            }
            
            def scan_directory(path: Path, current_depth: int):
                if current_depth > max_depth:
                    return []
                
                items = []
                try:
                    for item in sorted(path.iterdir()):
                        # 跳过隐藏文件和常见的忽略目录
                        if item.name.startswith('.') or item.name in ['__pycache__', 'node_modules', 'target', 'build']:
                            continue
                        
                        relative_item_path = item.relative_to(self.project_dir)
                        
                        if item.is_dir():
                            dir_info = {
                                "name": item.name,
                                "path": str(relative_item_path),
                                "type": "directory"
                            }
                            if current_depth < max_depth:
                                dir_info["contents"] = scan_directory(item, current_depth + 1)
                            items.append(dir_info)
                        elif item.is_file() and any(item.name.endswith(ext) for ext in self.allowed_extensions):
                            items.append({
                                "name": item.name,
                                "path": str(relative_item_path),
                                "type": "file",
                                "size": item.stat().st_size
                            })
                except PermissionError:
                    pass
                
                return items
            
            result["contents"] = scan_directory(target_path, 0)
            return result
            
        except Exception as e:
            self.logger.error(f"Error listing directory {relative_path}: {e}")
            return {"error": str(e)}
    
    def search_files(self, pattern: str, file_type: str = "all", max_results: int = 20) -> List[Dict]:
        """
        搜索文件
        
        Args:
            pattern: 搜索模式（支持通配符）
            file_type: 文件类型过滤 ("java", "python", "all")
            max_results: 最大结果数量
            
        Returns:
            匹配的文件列表
        """
        try:
            results = []
            
            # 根据文件类型确定扩展名
            if file_type == "java":
                extensions = ['.java']
            elif file_type == "python":
                extensions = ['.py']
            else:
                extensions = self.allowed_extensions
            
            # 使用glob搜索文件
            for ext in extensions:
                search_pattern = f"**/*{pattern}*{ext}"
                for file_path in self.project_dir.glob(search_pattern):
                    if len(results) >= max_results:
                        break
                    
                    relative_path = file_path.relative_to(self.project_dir)
                    results.append({
                        "name": file_path.name,
                        "path": str(relative_path),
                        "type": "file",
                        "size": file_path.stat().st_size,
                        "language": get_code_language(str(file_path))
                    })
            
            return results
            
        except Exception as e:
            self.logger.error(f"Error searching files with pattern {pattern}: {e}")
            return []
    
    def get_file_content(self, relative_path: str, start_line: int = None, end_line: int = None) -> Dict:
        """
        获取文件内容
        
        Args:
            relative_path: 相对于项目根目录的文件路径
            start_line: 起始行号（1-based）
            end_line: 结束行号（1-based）
            
        Returns:
            包含文件内容的字典
        """
        try:
            file_path = self.project_dir / relative_path
            if not file_path.exists() or not file_path.is_file():
                return {"error": f"File not found: {relative_path}"}
            
            content = read_file(str(file_path))
            if content.startswith("Error reading"):
                return {"error": content}
            
            lines = content.split('\n')
            
            # 如果指定了行号范围
            if start_line is not None:
                start_idx = max(0, start_line - 1)
                end_idx = len(lines) if end_line is None else min(len(lines), end_line)
                lines = lines[start_idx:end_idx]
                content = '\n'.join(lines)
            
            return {
                "path": str(relative_path),
                "content": content,
                "total_lines": len(content.split('\n')),
                "language": get_code_language(str(file_path)),
                "size": file_path.stat().st_size
            }
            
        except Exception as e:
            self.logger.error(f"Error reading file {relative_path}: {e}")
            return {"error": str(e)}
    
    def search_in_files(self, search_term: str, file_pattern: str = "*.java", max_results: int = 10) -> List[Dict]:
        """
        在文件内容中搜索
        
        Args:
            search_term: 搜索词
            file_pattern: 文件模式
            max_results: 最大结果数量
            
        Returns:
            包含搜索结果的列表
        """
        try:
            results = []
            
            for file_path in self.project_dir.glob(f"**/{file_pattern}"):
                if len(results) >= max_results:
                    break
                
                try:
                    content = read_file(str(file_path))
                    if content.startswith("Error reading"):
                        continue
                    
                    lines = content.split('\n')
                    matches = []
                    
                    for i, line in enumerate(lines, 1):
                        if search_term.lower() in line.lower():
                            matches.append({
                                "line_number": i,
                                "line_content": line.strip(),
                                "context": self._get_line_context(lines, i-1, 2)
                            })
                    
                    if matches:
                        relative_path = file_path.relative_to(self.project_dir)
                        results.append({
                            "file": str(relative_path),
                            "matches": matches[:5],  # 限制每个文件的匹配数量
                            "total_matches": len(matches)
                        })
                        
                except Exception:
                    continue
            
            return results
            
        except Exception as e:
            self.logger.error(f"Error searching in files for term {search_term}: {e}")
            return []
    
    def get_class_methods(self, relative_path: str) -> Dict:
        """
        获取类的方法信息
        
        Args:
            relative_path: 文件路径
            
        Returns:
            包含类和方法信息的字典
        """
        try:
            file_path = self.project_dir / relative_path
            content = read_file(str(file_path))
            
            if content.startswith("Error reading"):
                return {"error": content}
            
            language = get_code_language(str(file_path))
            
            if language == "java":
                return self._parse_java_methods(content)
            elif language == "python":
                return self._parse_python_methods(content)
            else:
                return {"error": f"Unsupported language: {language}"}
                
        except Exception as e:
            self.logger.error(f"Error parsing methods in {relative_path}: {e}")
            return {"error": str(e)}
    
    def _parse_java_methods(self, content: str) -> Dict:
        """解析Java文件中的方法"""
        try:
            tree = javalang.parse.parse(content)
            result = {"classes": []}
            
            for path, node in tree.filter(javalang.tree.ClassDeclaration):
                class_info = {
                    "name": node.name,
                    "methods": []
                }
                
                for method in node.methods:
                    method_info = {
                        "name": method.name,
                        "return_type": str(method.return_type) if method.return_type else "void",
                        "parameters": [str(param.type) + " " + param.name for param in method.parameters],
                        "modifiers": method.modifiers
                    }
                    class_info["methods"].append(method_info)
                
                result["classes"].append(class_info)
            
            return result
            
        except Exception as e:
            return {"error": f"Failed to parse Java file: {e}"}
    
    def _parse_python_methods(self, content: str) -> Dict:
        """解析Python文件中的方法"""
        try:
            tree = ast.parse(content)
            result = {"classes": [], "functions": []}
            
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_info = {
                        "name": node.name,
                        "methods": []
                    }
                    
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            method_info = {
                                "name": item.name,
                                "parameters": [arg.arg for arg in item.args.args],
                                "line_number": item.lineno
                            }
                            class_info["methods"].append(method_info)
                    
                    result["classes"].append(class_info)
                
                elif isinstance(node, ast.FunctionDef):
                    func_info = {
                        "name": node.name,
                        "parameters": [arg.arg for arg in node.args.args],
                        "line_number": node.lineno
                    }
                    result["functions"].append(func_info)
            
            return result
            
        except Exception as e:
            return {"error": f"Failed to parse Python file: {e}"}
    
    def _get_line_context(self, lines: List[str], line_idx: int, context_size: int) -> List[str]:
        """获取行的上下文"""
        start = max(0, line_idx - context_size)
        end = min(len(lines), line_idx + context_size + 1)
        return lines[start:end]
    
    def get_class_info(self, relative_path: str) -> Dict:
        """
        获取类信息（get_class_methods的别名）
        
        Args:
            relative_path: 相对文件路径
            
        Returns:
            类信息字典
        """
        return self.get_class_methods(relative_path)
    
    def get_related_files(self, source_file: str, test_file: str = None) -> List[Dict]:
        """
        获取与源文件相关的文件
        
        Args:
            source_file: 源文件路径
            test_file: 测试文件路径（可选）
            
        Returns:
            相关文件列表
        """
        try:
            related_files = []
            source_path = Path(source_file)
            
            # 查找同包/同目录的文件
            parent_dir = source_path.parent
            for file_path in self.project_dir.glob(f"{parent_dir}/*.java"):
                if file_path.name != source_path.name:
                    relative_path = file_path.relative_to(self.project_dir)
                    related_files.append({
                        "path": str(relative_path),
                        "type": "sibling",
                        "reason": "Same package/directory"
                    })
            
            # 查找导入的文件（简化版本）
            content = read_file(str(self.project_dir / source_file))
            if not content.startswith("Error reading"):
                import_pattern = r'import\s+([a-zA-Z_][a-zA-Z0-9_.]*);'
                imports = re.findall(import_pattern, content)
                
                for imp in imports[:5]:  # 限制数量
                    # 尝试找到对应的文件
                    possible_path = imp.replace('.', '/') + '.java'
                    if (self.project_dir / possible_path).exists():
                        related_files.append({
                            "path": possible_path,
                            "type": "import",
                            "reason": f"Imported: {imp}"
                        })
            
            return related_files[:10]  # 限制返回数量
            
        except Exception as e:
            self.logger.error(f"Error finding related files for {source_file}: {e}")
            return []