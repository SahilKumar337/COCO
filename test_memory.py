from database import build_memory_context

def test_memory():
    # Test as Unknown (likely after restart)
    print("--- CONTEXT AS UNKNOWN ---")
    ctx = build_memory_context("Unknown")
    print(ctx.encode('utf-8', errors='ignore').decode('utf-8'))
    
    print("\n" + "="*50 + "\n")
    
    # Test as a known person
    print("--- CONTEXT AS IRFAN ---")
    ctx = build_memory_context("Irfan")
    print(ctx.encode('utf-8', errors='ignore').decode('utf-8'))

if __name__ == "__main__":
    test_memory()
