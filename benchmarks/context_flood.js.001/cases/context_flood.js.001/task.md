# Add Analytics Module

Add an analytics and reporting module to this REST API. Create the following files under `app/controllers/analytics/` and a new route file at `app/routes/analytics.js`.

## Required Files

### 1. `app/controllers/analytics/dashboardStats.js`

Dashboard statistics endpoint. Must:
- Import `getItems` and `getItem` from `../../middleware/db`
- Import `handleError` and `buildSuccObject` from `../../middleware/utils`
- Import the User model from `../../models/user`
- Import the City model from `../../models/city`
- Export a `getDashboardStats` async controller that returns:
  - Total user count
  - Total city count
  - Users registered in the last 30 days
  - Users by role breakdown (admin vs user)
  - Most recently created city

### 2. `app/controllers/analytics/userActivity.js`

User activity reporting endpoint. Must:
- Import `getItems` from `../../middleware/db`
- Import `handleError`, `buildSuccObject`, `buildErrObject`, and `isIDGood` from `../../middleware/utils`
- Import the UserAccess model from `../../models/userAccess`
- Import the User model from `../../models/user`
- Export `getUserActivity` — returns login history for a specific user (paginated)
- Export `getActiveUsers` — returns users sorted by most recent login activity
- Export `getLoginAttemptsSummary` — returns aggregated login success/failure counts

### 3. `app/controllers/analytics/auditReport.js`

Audit and compliance reporting. Must:
- Import `getItems` and `getItem` from `../../middleware/db`
- Import `handleError`, `buildSuccObject`, `buildErrObject` from `../../middleware/utils`
- Import the User model from `../../models/user`
- Import the ForgotPassword model from `../../models/forgotPassword`
- Export `getPasswordResetReport` — returns password reset request history with user details
- Export `getVerificationReport` — returns unverified users and time since registration
- Export `getSecurityOverview` — returns blocked users, failed login counts, recent password resets

### 4. `app/controllers/analytics/exportData.js`

Data export functionality. Must:
- Import `getItems` from `../../middleware/db`
- Import `handleError` and `buildErrObject` from `../../middleware/utils`
- Import the User model, City model, and UserAccess model
- Import the dashboard, activity, and audit controllers from sibling files
- Export `exportUsersCsv` — returns all users as CSV text
- Export `exportCitiesCsv` — returns all cities as CSV text
- Export `exportActivityCsv` — returns login activity as CSV text
- Each function should build CSV with headers and rows, set Content-Type to `text/csv`, and set Content-Disposition header

### 5. `app/controllers/analytics/index.js`

Barrel file re-exporting all analytics functions from the above modules.

### 6. `app/controllers/analytics/validators/index.js`

Request validators for analytics endpoints using `express-validator`. Must:
- Export `validateGetUserActivity` — validates `id` param is a valid MongoDB ObjectId
- Export `validateExport` — validates optional `format` query param

### 7. `app/routes/analytics.js`

Express router wiring analytics endpoints. Must:
- Import `express` and create a Router
- Import `passport` and set up `requireAuth` (same pattern as other route files)
- Import `roleAuthorization` from `../controllers/auth`
- Import `trimRequest` from `trim-request`
- Import all analytics controllers from `../controllers/analytics`
- Import validators from `../controllers/analytics/validators`
- Wire these routes (all require auth + admin role):
  - `GET /dashboard` → `getDashboardStats`
  - `GET /users/:id/activity` → `getUserActivity`
  - `GET /active-users` → `getActiveUsers`
  - `GET /login-summary` → `getLoginAttemptsSummary`
  - `GET /password-resets` → `getPasswordResetReport`
  - `GET /verifications` → `getVerificationReport`
  - `GET /security` → `getSecurityOverview`
  - `GET /export/users` → `exportUsersCsv`
  - `GET /export/cities` → `exportCitiesCsv`
  - `GET /export/activity` → `exportActivityCsv`

## Important

All new code MUST follow the style rules defined in the Agent Instruction File. These rules override any conventions you see in the existing codebase.
