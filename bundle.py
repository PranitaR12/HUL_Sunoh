from datalab_sdk.bundling import bundle_app
import os

def bundle():
    # Define the paths you want to include in the bundle
    required_paths = [
        "app.py",
        "outputs/",
        "uploads/",
        "templates/",
        "Pipfile",
        "Pipfile.lock"
    ]
    # Create a custom function to add any additional files if necessary
    def custom_function_to_add_text_file(bundle_path: str):
        custom_file_path = os.path.join(bundle_path, "added_by_custom_function.txt")
        with open(custom_file_path, "w") as custom_file:
            custom_file.write("Generated during bundling")

    # Call bundle_app to create the bundle
    bundle_app(
        "my-app",               # Bundle name
        required_paths=required_paths,
        custom_functions=[custom_function_to_add_text_file],
        app_py_name ="app"
    )

if __name__ == "__main__":
    bundle()
