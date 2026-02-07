#!/bin/bash
set -e

# If UPDATE_SCRAPERS=true, update recipe_scrapers. 
# Before setting this environment variable, try updating the container.
if [ "$UPDATE_SCRAPERS" = "true" ]; then
    echo "UPDATE_SCRAPERS is active. Upgrading libraries..."
    pip install --user --upgrade recipe-scrapers
    echo "--- Update Complete ---"
fi

echo "--- Starting LocalToast Supervisor ---"
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf