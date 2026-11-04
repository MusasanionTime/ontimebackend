from app.main import app

print("Registered authentication routes:")
found = False

for route in app.routes:
    if hasattr(route, "routes"):
        for child in route.routes:
            path = getattr(child, "path", "")
            methods = getattr(child, "methods", set()) or set()
            if "login" in path.lower() or "auth" in path.lower():
                print(",".join(sorted(methods)), path)
                found = True
    else:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if "login" in path.lower() or "auth" in path.lower():
            print(",".join(sorted(methods)), path)
            found = True

if not found:
    print("No matching routes found in the inspected router objects.")
