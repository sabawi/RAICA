
import sys
from pathlib import Path

# Mocking the environment
sys.path.append('/home/sabawi/Development/RAICA/agents/coding_agent')
from services.dependency_graph import DependencyGraphService

def test_dependency_graph():
    print("Testing DependencyGraphService...")
    
    # Setup dummy project structure
    # lib.py
    # app.py -> imports lib
    # test.py -> imports app
    
    Path("lib.py").write_text("def hello(): pass")
    Path("app.py").write_text("import lib\ndef run(): lib.hello()")
    Path("test.py").write_text("import app\ndef test_run(): app.run()")
    
    graph = DependencyGraphService(Path("."))
    graph.build_graph()
    
    print("\n1. Testing Dependencies (Forward)")
    deps = graph.get_dependencies("app.py")
    print(f"app.py imports: {deps}")
    if "lib.py" in deps:
        print("✅ app.py correctly depends on lib.py")
    else:
        print("❌ Failed to detect dependency")

    print("\n2. Testing Dependents (Reverse)")
    dependents = graph.get_dependents("lib.py", recursive=True)
    print(f"lib.py dependents (recursive): {dependents}")
    
    # Should Include app.py (direct) and test.py (transitive via app.py)
    # Actually, test.py imports 'app', app imports 'lib'. 
    # Does 'test.py' depend on 'lib'? Transitive yes. 
    # My simple BFS should catch it IF 'app' is in graph.
    
    if "app.py" in dependents and "test.py" in dependents:
        print("✅ Correctly identified direct (app) and transitive (test) dependents")
    else:
        print(f"❌ Failed. Expected app.py and test.py, got {dependents}")

    # Cleanup
    for f in ["lib.py", "app.py", "test.py"]:
        if Path(f).exists(): Path(f).unlink()

if __name__ == "__main__":
    test_dependency_graph()
