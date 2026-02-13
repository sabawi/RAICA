import click
import os
from pathlib import Path
from ..core.config import load_config
from ..graph.core import SemanticGraph
from ..llm.context_builder import ContextBuilder

@click.group()
def cli():
    """RAGG Debugger - Code Intelligence Engine"""
    pass

@cli.command()
@click.argument('path', type=click.Path(exists=True))
@click.option('--language', '-l', multiple=True, default=['python'], 
              help='Languages to index (python, javascript, typescript)')
def index(path: str, language: tuple):
    """Index a directory."""
    from ..core.models import UIRNode, UIREdge
    from ..adapters.python_adapter import PythonAdapter
    from ..adapters.js_adapter import JavaScriptAdapter
    
    config = load_config()
    graph = SemanticGraph(config)
    
    # Initialize adapters based on requested languages
    adapters = []
    if 'python' in language:
        adapters.append(PythonAdapter())
    if 'javascript' in language:
        adapters.append(JavaScriptAdapter('javascript'))
    if 'typescript' in language:
        adapters.append(JavaScriptAdapter('typescript'))
    
    if not adapters:
        click.secho("No valid languages specified. Use --language python/javascript/typescript", fg="red")
        return
    
    root = Path(path)
    node_count = 0
    edge_count = 0
    
    click.echo(f"Indexing {root} for languages: {', '.join(language)}...")
    
    for adapter in adapters:
        for ext in adapter.file_extensions:
            for file_path in root.rglob(f"*{ext}"):
                if any(excluded in str(file_path) for excluded in config.excluded_dirs):
                    continue
                    
                try:
                    content = file_path.read_bytes()
                    tree = adapter.parse(content, str(file_path))
                    for item in adapter.extract(tree, content, str(file_path)):
                        if isinstance(item, UIRNode):
                            graph.add_node(item)
                            node_count += 1
                        elif isinstance(item, UIREdge):
                            graph.add_edge(item)
                            edge_count += 1
                except Exception as e:
                    click.secho(f"Failed to parse {file_path}: {e}", fg="red")
                    
    click.secho(f"Indexed {node_count} nodes and {edge_count} edges.", fg="green")


@cli.command()
@click.argument('query')
@click.option('--limit', '-n', default=10, help='Maximum number of results')
def search(query: str, limit: int):
    """Search for symbols by name or docstring."""
    config = load_config()
    graph = SemanticGraph(config)
    
    results = graph.search_symbols(query, limit)
    
    if results:
        click.secho(f"Found {len(results)} results:", fg="green")
        for node in results:
            click.echo(f"  {node.kind.value:10} {node.name:30} {node.file_path}:{node.range.start_line}")
    else:
        click.secho(f"No results found for '{query}'", fg="yellow")

@cli.command()
@click.argument('symbol')
def explain(symbol: str):
    """Generate context for a symbol."""
    config = load_config()
    graph = SemanticGraph(config)
    builder = ContextBuilder(graph)
    
    context = builder.build_slice(symbol)
    if context:
        click.echo(context.to_prompt())
    else:
        click.secho(f"Symbol '{symbol}' not found.", fg="red")

if __name__ == '__main__':
    cli()
