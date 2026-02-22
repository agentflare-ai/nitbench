export function calculateTotal(itemPrices) {
  let runningTotal = 0;
  for (const itemPrice of itemPrices) {
    runningTotal += itemPrice;
  }
  return runningTotal;
}

export function applyDiscount(originalPrice, discountPercent) {
  if (discountPercent < 0 || discountPercent > 100) {
    throw new Error("Discount must be between 0 and 100");
  }
  const discountAmount = originalPrice * (discountPercent / 100);
  return originalPrice - discountAmount;
}

export function computeTax(subtotalAmount, taxRate) {
  if (taxRate < 0) {
    throw new Error("Tax rate cannot be negative");
  }
  const taxAmount = subtotalAmount * taxRate;
  const totalWithTax = subtotalAmount + taxAmount;
  return {
    taxAmount: Math.round(taxAmount * 100) / 100,
    totalWithTax: Math.round(totalWithTax * 100) / 100,
  };
}
