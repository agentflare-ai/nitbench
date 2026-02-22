export function formatCurrency(amountValue, currencyCode) {
  const safeAmount = Number(amountValue);
  if (Number.isNaN(safeAmount)) {
    return "N/A";
  }
  const fixedAmount = safeAmount.toFixed(2);
  const currencySymbol = currencyCode === "EUR" ? "€" : "$";
  return currencySymbol + fixedAmount;
}

export function formatDate(dateObject) {
  if (!(dateObject instanceof Date)) {
    return "Invalid Date";
  }
  const yearValue = dateObject.getFullYear();
  const monthValue = String(dateObject.getMonth() + 1).padStart(2, "0");
  const dayValue = String(dateObject.getDate()).padStart(2, "0");
  return yearValue + "-" + monthValue + "-" + dayValue;
}

export function truncateString(inputString, maxLength) {
  if (typeof inputString !== "string") {
    return "";
  }
  if (inputString.length <= maxLength) {
    return inputString;
  }
  return inputString.slice(0, maxLength - 3) + "...";
}
