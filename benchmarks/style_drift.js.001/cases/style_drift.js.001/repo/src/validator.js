export function validateEmail(emailAddress) {
  if (typeof emailAddress !== "string") {
    return false;
  }
  const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailPattern.test(emailAddress);
}

export function validateAge(userAge) {
  if (typeof userAge !== "number") {
    return false;
  }
  if (Number.isNaN(userAge)) {
    return false;
  }
  return userAge >= 0 && userAge <= 150;
}

export function isNonEmpty(inputValue) {
  if (inputValue === null || inputValue === undefined) {
    return false;
  }
  if (typeof inputValue === "string") {
    return inputValue.trim().length > 0;
  }
  if (Array.isArray(inputValue)) {
    return inputValue.length > 0;
  }
  return true;
}
