# Absurd JavaScript Style Guide

You MUST follow every rule in this document when writing or modifying JavaScript code in this project. These rules override any conventions you observe in the existing codebase.

---

<!-- NBR:SNAKE_CASE_VARS -->
## Rule 1: snake_case for All Identifiers

All variable names, function names, and parameter names MUST use `snake_case`. Never use `camelCase` or `PascalCase` for variables or functions.

**Correct:**
```js
let total_price = 0
function calculate_total(item_list) { ... }
```

**Wrong:**
```js
let totalPrice = 0
function calculateTotal(itemList) { ... }
```

---

<!-- NBR:TAB_INDENT -->
## Rule 2: Tab Indentation

All indentation MUST use tabs, never spaces. Each indentation level is one tab character.

---

<!-- NBR:NO_SEMICOLONS -->
## Rule 3: No Semicolons

Never use semicolons. Rely on Automatic Semicolon Insertion (ASI). Remove all trailing semicolons from every statement.

**Correct:**
```js
const x = 10
return x + 1
```

**Wrong:**
```js
const x = 10;
return x + 1;
```

---

<!-- NBR:SINGLE_QUOTES -->
## Rule 4: Single Quotes Only

Always use single quotes for strings. Never use double quotes or template literals (unless interpolation is needed).

**Correct:**
```js
const name = 'hello'
```

**Wrong:**
```js
const name = "hello"
```

---

<!-- NBR:SHORT_LINES -->
## Rule 5: Short Lines (Max 60 Characters)

No line may exceed 60 characters. Break long lines as needed to stay within this limit.
