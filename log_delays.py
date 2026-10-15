from datetime import datetime
import os
import sqlite3
import requests

CLIENT_ID = os.environ.get("SCHIPHOL_APP_ID")
CLIENT_SECRET = os.environ.get("SCHIPHOL_APP_KEY")


def get_schiphol_token(client_id: str, client_secret: str) -> str:
  """Haalt automatisch een tijdelijk bearer token op via OAuth."""
  auth_url = "https://api.auth.schiphol.nl/oauth/token"
  payload = {
      "grant_type": "client_credentials",
      "client_id": client_id,
      "client_secret": client_secret,
      "audience": "https://api.schiphol.nl/public",
  }
  headers = {"Content-Type": "application/x-www-form-urlencoded"}

  response = requests.post(auth_url, data=payload, headers=headers)
  response.raise_for_status()
  return response.json()["access_token"]


def main():
  if not CLIENT_ID or not CLIENT_SECRET:
    raise ValueError(
        "SCHIPHOL_APP_ID of SCHIPHOL_APP_KEY ontbreekt in omgevingsvariabelen."
    )

  # 1. Access token ophalen
  token = get_schiphol_token(CLIENT_ID, CLIENT_SECRET)

  # 2. Database klaarzetten
  conn = sqlite3.connect("klm_delays.db")
  c = conn.cursor()
  c.execute("""CREATE TABLE IF NOT EXISTS flights (
                    flight_id TEXT PRIMARY KEY,
                    flight_name TEXT,
                    destination TEXT,
                    schedule_time TEXT,
                    actual_time TEXT,
                    delay_minutes INTEGER,
                    date TEXT
                )""")

  # 3. KLM vertrekken van vandaag ophalen
  today = datetime.utcnow().strftime("%Y-%m-%d")
  flights_url = "https://api.schiphol.nl/public/public-flights/v4/flights"
  headers = {
      "Authorization": f"Bearer {token}",
      "Accept": "application/json",
      "ResourceVersion": "v4",
  }
  params = {"flightDirection": "D", "airline": "KL", "scheduleDate": today}

  resp = requests.get(flights_url, headers=headers, params=params)
  resp.raise_for_status()

  flights = resp.json().get("flights", [])
  for f in flights:
    flight_name = f.get("flightName")
    schedule_time = f.get("scheduleTime")  # bijv. '14:30:00'
    actual_time = f.get("actualOffBlockTime")  # werkelijk vertrek

    delay = 0
    if actual_time and schedule_time:
      try:
        fmt = "%H:%M:%S"
        t1 = datetime.strptime(schedule_time, fmt)
        t2 = datetime.strptime(actual_time.split("T")[-1][:8], fmt)
        delay = max(0, int((t2 - t1).total_seconds() / 60))
      except Exception:
        pass

    destinations = f.get("route", {}).get("destinations", ["UNKNOWN"])
    dest = destinations[0] if destinations else "UNKNOWN"
    flight_id = f"{flight_name}_{today}"

    c.execute(
        """INSERT INTO flights VALUES (?, ?, ?, ?, ?, ?, ?)
                 ON CONFLICT(flight_id) DO UPDATE SET
                 actual_time=excluded.actual_time,
                 delay_minutes=excluded.delay_minutes""",
        (
            flight_id,
            flight_name,
            dest,
            schedule_time,
            actual_time,
            delay,
            today,
        ),
    )

  # 4. Rollend venster van 30 dagen behouden en database compact houden
  c.execute("DELETE FROM flights WHERE date < date('now', '-30 days')")
  c.execute("VACUUM")

  conn.commit()
  conn.close()
  print(f"Succesvol verwerkt: {len(flights)} KLM vluchten voor {today}.")


if __name__ == "__main__":
  main()
