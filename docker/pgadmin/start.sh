#!/bin/sh
# Starts pgAdmin already connected to this project's database, so nobody has to type a host, user or password.
# The connection is written from the same POSTGRES_* settings docker-compose.yml gives the database.
set -eu

# libpq's password file ("host:port:database:user:password"): lets pgAdmin connect without asking.
printf 'db:5432:*:%s:%s\n' "$POSTGRES_USER" "$POSTGRES_PASSWORD" > /tmp/pgpass
chmod 600 /tmp/pgpass

cat > /tmp/servers.json <<JSON
{
  "Servers": {
    "1": {
      "Name": "SupportNova (Docker)",
      "Group": "Servers",
      "Host": "db",
      "Port": 5432,
      "MaintenanceDB": "$POSTGRES_DB",
      "Username": "$POSTGRES_USER",
      "SSLMode": "prefer",
      "PassFile": "/tmp/pgpass"
    }
  }
}
JSON

export PGPASSFILE=/tmp/pgpass   # every connection pgAdmin makes finds the password here
export PGADMIN_SERVER_JSON_FILE=/tmp/servers.json
export PGADMIN_REPLACE_SERVERS_ON_STARTUP=True   # re-read the connection on every start, so a changed .env is picked up
exec /entrypoint.sh
