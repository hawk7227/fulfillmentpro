// Firebase Cloud Messaging Service Worker
// Handles push notifications when app is in background

importScripts('https://www.gstatic.com/firebasejs/10.7.1/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.7.1/firebase-messaging-compat.js');

// Initialize Firebase (use exact config from screenshot)
firebase.initializeApp({
  apiKey: "AIzaSyGdeG8AaIZD9CP1P1ul8FKHjTpv4Uwjzjg",
  authDomain: "fulfillmentpro-b920a.firebaseapp.com",
  projectId: "fulfillmentpro-b920a",
  storageBucket: "fulfillmentpro-b920a.firebasestorage.app",
  messagingSenderId: "634584635129",
  appId: "1:634584635129:web:0b76ac4d53e870d8493428"
});

const messaging = firebase.messaging();

// Handle background messages
messaging.onBackgroundMessage((payload) => {
  console.log('[firebase-messaging-sw.js] Received background message:', payload);
  
  const notificationTitle = payload.notification?.title || 'FulfillmentPro';
  const notificationOptions = {
    body: payload.notification?.body || 'New notification',
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    tag: payload.data?.type || 'general',
    requireInteraction: payload.data?.type === 'verification_required',
    data: payload.data,
    actions: payload.data?.type === 'verification_required' ? [
      { action: 'open', title: '🔐 Open Dashboard' }
    ] : []
  };

  return self.registration.showNotification(notificationTitle, notificationOptions);
});

// Handle notification clicks
self.addEventListener('notificationclick', (event) => {
  console.log('[firebase-messaging-sw.js] Notification clicked');
  event.notification.close();
  
  // Open or focus dashboard
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then((clientList) => {
        // If dashboard is already open, focus it
        for (let client of clientList) {
          if (client.url.includes(self.registration.scope) && 'focus' in client) {
            return client.focus();
          }
        }
        // Otherwise open new window
        if (clients.openWindow) {
          return clients.openWindow('/');
        }
      })
  );
});
