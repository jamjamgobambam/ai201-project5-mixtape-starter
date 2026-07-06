if __name__ == "__main__":
    import subprocess
    import sys
    
    # Run the module using the virtual environment's python interpreter
    try:
        subprocess.run([sys.executable, "-m", "services.feed_service"], check=True)
    except Exception as e:
        print(f"Error running feed service: {e}")
