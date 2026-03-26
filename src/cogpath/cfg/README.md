## Control flow analysis 

To setup `comex` module for further program analysis implementation using the source code in your python environment:

```console
pip install -r requirements-dev.txt
```

To run `comex` module as script 

```console
python3 -m comex --lang "java" --code-file path_to_file/code_file.java
```

The attributes and options supported can be viewed by running:

```console
python3 -m comex --help
```
The default graph is control flow graph and the default output is in json format.
