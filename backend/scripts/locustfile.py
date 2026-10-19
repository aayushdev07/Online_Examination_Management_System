"""Optional Locust scenario (pip install -r requirements-dev.txt).

    locust -f scripts/locustfile.py --host http://127.0.0.1:8000
"""

from locust import HttpUser, between, task


class FacultyUser(HttpUser):
    wait_time = between(0.2, 1.0)

    def on_start(self):
        r = self.client.post("/api/auth/login", json={"username": "rdeshpande", "password": "Password@123",
                                                      "account_type": "STAFF"})
        self.client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    @task(4)
    def exams(self):
        self.client.get("/api/exams")

    @task(2)
    def performance(self):
        self.client.get("/api/results/performance")

    @task(2)
    def attempts(self):
        self.client.get("/api/attempts?page_size=20", name="/api/attempts")

    @task(1)
    def report(self):
        self.client.get("/api/reports/subject_performance", name="/api/reports/[id]")

    @task(1)
    def health(self):
        self.client.get("/api/health")
