#!/usr/bin/env python3
"""Run integration tests and display results"""
import subprocess
import sys
import os

def run_tests():
    """Run all integration tests"""
    print("=" * 70)
    print("RAG System Integration Tests")
    print("=" * 70)
    print()
    
    test_files = [
        "app/tests/integration/test_rag_workflow.py",
        "app/tests/integration/test_hybrid_retrieval.py",
        "app/tests/integration/test_error_handling.py",
        "app/tests/integration/test_performance.py",
    ]
    
    results = {}
    
    for test_file in test_files:
        if not os.path.exists(test_file):
            print(f"⚠ Skipping {test_file} (not found)")
            continue
        
        print(f"\n{'='*70}")
        print(f"Running: {test_file}")
        print(f"{'='*70}")
        
        try:
            result = subprocess.run(
                ["python3", "-m", "pytest", test_file, "-v", "--tb=short"],
                capture_output=True,
                text=True,
                cwd=os.path.dirname(__file__)
            )
            
            print(result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
            
            results[test_file] = result.returncode == 0
            
        except Exception as e:
            print(f"Error running tests: {e}")
            results[test_file] = False
    
    # Summary
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_file, passed_test in results.items():
        status = "✓ PASSED" if passed_test else "✗ FAILED"
        print(f"{status}: {test_file}")
    
    print(f"\nTotal: {passed}/{total} test suites passed")
    
    if passed == total:
        print("\n✓ All integration tests passed!")
        return 0
    else:
        print(f"\n✗ {total - passed} test suite(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(run_tests())

