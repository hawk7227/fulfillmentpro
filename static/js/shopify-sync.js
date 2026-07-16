async function checkShopifyStatus() {
  const status = document.getElementById("shopify-status");
  if (!status) return;

  try {
    const response = await fetch("/api/shopify/status");
    const data = await response.json();

    status.textContent = data.connected
      ? `Connected: ${data.shop}`
      : "Not connected";
  } catch (error) {
    status.textContent = "Connection check failed";
  }
}

async function syncShopify() {
  const button = document.getElementById("sync-shopify-button");
  if (!button) return;

  button.disabled = true;
  button.textContent = "Syncing...";

  try {
    const response = await fetch("/api/shopify/sync", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      }
    });

    const result = await response.json();

    if (!response.ok) {
      alert(result.error || "Shopify sync failed");
    } else {
      alert("Shopify sync completed");
      window.location.reload();
    }
  } catch (error) {
    alert("Shopify sync failed");
  } finally {
    button.disabled = false;
    button.textContent = "Sync Shopify";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  checkShopifyStatus();

  const button = document.getElementById("sync-shopify-button");
  if (button) {
    button.addEventListener("click", syncShopify);
  }
});
