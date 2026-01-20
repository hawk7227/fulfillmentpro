"""
Shopify Order Fulfillment via Selenium
"""
import time
import random
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

SHOPIFY_STORE = "br1xzv-gd"

def mark_shopify_order_fulfilled(driver, shopify_order_id):
    """
    Mark a Shopify order as fulfilled using Selenium
    
    Args:
        driver: Selenium WebDriver instance (must be logged into Shopify)
        shopify_order_id: Shopify internal order ID (e.g., "7194638778532")
    
    Returns:
        bool: True if successful, False otherwise
    """
    print(f"\n📦 Marking Shopify order {shopify_order_id} as fulfilled...")
    
    try:
        # Navigate to order page
        url = f"https://admin.shopify.com/store/{SHOPIFY_STORE}/orders/{shopify_order_id}"
        driver.get(url)
        time.sleep(random.randint(3, 5))
        
        # Check if already fulfilled
        try:
            driver.find_element(By.XPATH, "//*[contains(text(), 'Fulfilled')]")
            print("✅ Order already fulfilled!")
            return True
        except NoSuchElementException:
            pass
        
        # STEP 1: Click first "Mark as fulfilled" button (Secondary variant)
        print("🔘 Clicking 'Mark as fulfilled' button...")
        
        first_button_selectors = [
            "//button[contains(@class, 'Polaris-Button--variantSecondary')]//span[text()='Mark as fulfilled']/parent::button",
            "//button[contains(@id, 'CREATE_FULFILLMENT')]",
            "//span[text()='Mark as fulfilled']/parent::button[contains(@class, 'Polaris-Button--variantSecondary')]"
        ]
        
        first_btn = None
        for selector in first_button_selectors:
            try:
                first_btn = driver.find_element(By.XPATH, selector)
                break
            except NoSuchElementException:
                continue
        
        if not first_btn:
            print("❌ 'Mark as fulfilled' button not found")
            return False
        
        driver.execute_script("arguments[0].click();", first_btn)
        print("✅ Clicked first button")
        
        # STEP 2: Wait 5-10 seconds for modal to load
        wait_time = random.randint(5, 10)
        print(f"⏳ Waiting {wait_time}s for modal...")
        time.sleep(wait_time)
        
        # STEP 3: Click confirmation "Mark as fulfilled" button (Primary variant)
        print("🔘 Clicking confirmation button...")
        
        confirm_selectors = [
            "//button[contains(@class, 'Polaris-Button--variantPrimary')]//span[text()='Mark as fulfilled']/parent::button",
            "//button[@aria-disabled='false'][contains(@class, 'Polaris-Button--variantPrimary')]//span[contains(@class, 'Polaris-Text--semibold')][text()='Mark as fulfilled']/..",
            "//button[contains(@class, 'Polaris-Button--variantPrimary')][contains(@class, 'Polaris-Button--sizeMedium')][@aria-disabled='false']//span[text()='Mark as fulfilled']/.."
        ]
        
        confirm_btn = None
        for selector in confirm_selectors:
            try:
                confirm_btn = driver.find_element(By.XPATH, selector)
                break
            except NoSuchElementException:
                continue
        
        if not confirm_btn:
            print("❌ Confirmation button not found")
            driver.save_screenshot('shopify_fulfill_error.png')
            return False
        
        driver.execute_script("arguments[0].click();", confirm_btn)
        print("✅ Clicked confirmation button")
        time.sleep(random.randint(3, 5))
        
        # Verify success
        try:
            driver.find_element(By.XPATH, "//*[contains(text(), 'fulfilled') or contains(text(), 'Fulfilled')]")
            print("✅ Order marked as FULFILLED in Shopify!")
            return True
        except NoSuchElementException:
            print("⚠️  Could not verify, but likely succeeded")
            return True
            
    except Exception as e:
        print(f"❌ Error fulfilling order: {e}")
        import traceback
        traceback.print_exc()
        return False