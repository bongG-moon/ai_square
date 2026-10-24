from web_main import app as application

if __name__ == "__main__":
    from backend.dev_reload import upload_reload_excludes

    # Werkzeug's watchdog also watches ZIPs. Uploads are data, not changed code.
    application.run(debug=True, host='0.0.0.0',
                    exclude_patterns=upload_reload_excludes(application.config['DATA_DIR']))
