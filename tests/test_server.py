import unittest
from fastapi.testclient import TestClient
from fashion_stt.server import app


class TestFashionSTTServer(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)

    def test_health_check(self):
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["language"], "en")

    def test_extract_endpoint(self):
        payload = {"text": "find me an out culture dress in she fawn under 500 dollars"}
        res = self.client.post("/api/extract", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["clean_text"], "find me an haute couture dress in chiffon under 500 dollars")
        self.assertIn("chiffon", data["entities"]["materials"])
        self.assertEqual(data["entities"]["price"]["max"], 500.0)

    def test_catalog_endpoint(self):
        # 1. All items
        res = self.client.get("/api/catalog")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["count"], 12)

        # 2. Filter by material=silk
        res_silk = self.client.get("/api/catalog?material=silk")
        data_silk = res_silk.json()
        self.assertTrue(data_silk["count"] >= 1)
        self.assertTrue(all("silk" in item["material"].lower() for item in data_silk["items"]))

        # 3. Filter by max_price=100
        res_price = self.client.get("/api/catalog?max_price=100")
        data_price = res_price.json()
        self.assertTrue(all(item["price"] <= 100 for item in data_price["items"]))


if __name__ == "__main__":
    unittest.main()
