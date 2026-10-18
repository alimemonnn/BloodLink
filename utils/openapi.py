"""The public API description (OpenAPI 3.0). Kept in code so a test can check it matches the routes."""

BLOOD = {"type": "string", "enum": ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]}


def spec(version="1.0.0"):
    err = {"description": "Error", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
    page = [{"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}},
            {"name": "offset", "in": "query", "schema": {"type": "integer", "minimum": 0, "default": 0}}]
    ok = lambda ref: {"description": "OK", "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{ref}"}}}}
    return {
        "openapi": "3.0.3",
        "info": {"title": "BloodLink public API", "version": version,
                 "description": ("Read-only, public data about blood requests, hospital stock and donation camps. "
                                 "It never contains patient or donor names, phone numbers or emails. "
                                 "Limit: 60 requests per minute per IP address. Stock is self-reported by hospitals.")},
        "servers": [{"url": "/api/v1"}],
        "paths": {
            "/health": {"get": {"summary": "Is the service up?", "responses": {"200": ok("Health")}}},
            "/stats": {"get": {"summary": "Headline numbers", "responses": {"200": ok("Stats")}}},
            "/requests": {"get": {
                "summary": "Open blood requests (patients shown as initials)",
                "parameters": page + [
                    {"name": "blood_group", "in": "query", "schema": BLOOD},
                    {"name": "city", "in": "query", "schema": {"type": "string"}},
                    {"name": "urgency", "in": "query", "schema": {"type": "string", "enum": ["Normal", "Urgent", "Critical"]}}],
                "responses": {"200": ok("RequestList"), "429": err}}},
            "/stock": {"get": {"summary": "Self-reported blood stock at verified hospitals",
                               "parameters": [{"name": "city", "in": "query", "schema": {"type": "string"}}],
                               "responses": {"200": ok("StockList"), "429": err}}},
            "/camps": {"get": {"summary": "Upcoming donation camps", "parameters": page + [
                {"name": "city", "in": "query", "schema": {"type": "string"}}],
                               "responses": {"200": ok("CampList"), "429": err}}},
            "/certificates/{code}": {"get": {
                "summary": "Check a donation certificate code",
                "parameters": [{"name": "code", "in": "path", "required": True, "schema": {"type": "string"},
                                "example": "BL-00017-AB12CD34"}],
                "responses": {"200": ok("CertificateCheck"), "429": err}}},
        },
        "components": {"schemas": {
            "Error": {"type": "object", "properties": {"error": {"type": "string"}}},
            "Health": {"type": "object", "properties": {"status": {"type": "string"}, "version": {"type": "string"}}},
            "Stats": {"type": "object", "properties": {
                "registered_donors": {"type": "integer"}, "open_requests": {"type": "integer"},
                "partner_hospitals": {"type": "integer"}, "requests_fulfilled": {"type": "integer"}}},
            "Request": {"type": "object", "properties": {
                "id": {"type": "integer"}, "blood_group": BLOOD, "units_remaining": {"type": "integer"},
                "urgency": {"type": "string"}, "city": {"type": "string"}, "hospital": {"type": "string"},
                "patient": {"type": "string", "description": "Initials only"},
                "required_by": {"type": "string", "format": "date", "nullable": True}}},
            "RequestList": {"type": "object", "properties": {
                "items": {"type": "array", "items": {"$ref": "#/components/schemas/Request"}},
                "total": {"type": "integer"}, "limit": {"type": "integer"}, "offset": {"type": "integer"}}},
            "StockList": {"type": "object", "properties": {
                "note": {"type": "string"}, "items": {"type": "array", "items": {"type": "object", "properties": {
                    "hospital": {"type": "string"}, "city": {"type": "string"}, "updated_at": {"type": "string"},
                    "units": {"type": "object", "additionalProperties": {"type": "integer"}}}}}}},
            "CampList": {"type": "object", "properties": {
                "items": {"type": "array", "items": {"type": "object", "properties": {
                    "id": {"type": "integer"}, "title": {"type": "string"}, "hospital": {"type": "string"},
                    "venue": {"type": "string"}, "city": {"type": "string"}, "starts_at": {"type": "string"},
                    "ends_at": {"type": "string"}, "places_left": {"type": "integer"}}}},
                "total": {"type": "integer"}, "limit": {"type": "integer"}, "offset": {"type": "integer"}}},
            "CertificateCheck": {"type": "object", "properties": {
                "valid": {"type": "boolean"}, "donor": {"type": "string", "description": "First name and initial"},
                "units": {"type": "integer"}, "date": {"type": "string"}, "hospital": {"type": "string"}}},
        }},
    }
