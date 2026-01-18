// firebase-config.js - Production Configuration
import { initializeApp } from 'https://www.gstatic.com/firebasejs/10.7.1/firebase-app.js';
import { getMessaging, getToken, onMessage } from 'https://www.gstatic.com/firebasejs/10.7.1/firebase-messaging.js';

const firebaseConfig = {
  apiKey: "AIzaSyCdeG8AaIZD9CP1Piul8FKHjTpv4Uwjzjg",
  authDomain: "fulfillmentpro-b920a.firebaseapp.com",
  projectId: "fulfillmentpro-b920a",
  storageBucket: "fulfillmentpro-b920a.firebasestorage.app",
  messagingSenderId: "634584635129",
  appId: "1:634584635129:web:0b76ac4d53e870d8493428"
};

const app = initializeApp(firebaseConfig);
const messaging = getMessaging(app);

export async function requestNotificationPermission() {
  try {
    console.log('🔔 Requesting notification permission...');
    
    const permission = await Notification.requestPermission();
    
    if (permission === 'granted') {
      console.log('✅ Notification permission granted');
      
      const token = await getToken(messaging, {
        vapidKey: 'BPpg6Bgxk2wvRzgfC_JPHbQApUwNBOZ9pGfNnbzXqJ1yNrGnOp-eC37_cHrTsyX1BfKUiTaoixkctNjrOmarKW8'
      });
      
      if (token) {
        console.log('📱 FCM Token:', token);
        
        // Send token to backend
        const response = await fetch('/api/push/subscribe', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            token: token,
            device_label: `${navigator.platform} - ${navigator.userAgent.substring(0, 50)}`
          })
        });
        
        if (response.ok) {
          console.log('✅ Push notifications enabled and registered');
          showNotificationSuccess();
          return token;
        } else {
          console.error('❌ Failed to register token with backend');
        }
      } else {
        console.error('❌ No FCM token received');
      }
    } else if (permission === 'denied') {
      console.warn('🚫 Notification permission denied');
      showNotificationDenied();
    } else {
      console.log('⚠️ Notification permission dismissed');
    }
    
    return null;
  } catch (error) {
    console.error('❌ Error requesting notification permission:', error);
    return null;
  }
}

// Handle foreground messages
onMessage(messaging, (payload) => {
  console.log('📬 Foreground push notification received:', payload);
  
  const notificationTitle = payload.notification?.title || 'FulfillmentPro';
  const notificationOptions = {
    body: payload.notification?.body || 'New notification',
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    tag: payload.data?.type || 'general',
    requireInteraction: false,
    data: payload.data
  };
  
  // Show browser notification
  if (Notification.permission === 'granted') {
    const notification = new Notification(notificationTitle, notificationOptions);
    
    notification.onclick = function() {
      console.log('Notification clicked');
      window.focus();
      
      // Navigate based on notification type
      if (payload.data?.type === 'verification_required') {
        window.showPage?.('verification');
      } else if (payload.data?.type === 'new_order') {
        window.showPage?.('orders');
      }
      
      notification.close();
    };
    
    // Auto-close after 10 seconds
    setTimeout(() => notification.close(), 10000);
  }
});

function showNotificationSuccess() {
  const banner = document.createElement('div');
  banner.className = 'fixed top-4 left-1/2 transform -translate-x-1/2 bg-green-500 text-white px-6 py-3 rounded-xl shadow-lg z-50 font-bold text-sm';
  banner.textContent = '✅ Push notifications enabled!';
  document.body.appendChild(banner);
  setTimeout(() => banner.remove(), 3000);
}

function showNotificationDenied() {
  const banner = document.createElement('div');
  banner.className = 'fixed top-4 left-1/2 transform -translate-x-1/2 bg-red-500 text-white px-6 py-3 rounded-xl shadow-lg z-50 font-bold text-sm';
  banner.textContent = '🚫 Notifications blocked. Enable in browser settings.';
  document.body.appendChild(banner);
  setTimeout(() => banner.remove(), 5000);
}


export { messaging };


