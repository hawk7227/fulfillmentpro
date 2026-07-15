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

let audioCtx = null;
let soundUnlocked = false;
let lastOrderCountForSound = null;
let orderSoundPollStarted = false;

function getAudioContext() {
  const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextCtor) return null;
  if (!audioCtx) audioCtx = new AudioContextCtor();
  if (audioCtx.state === 'suspended') audioCtx.resume();
  return audioCtx;
}

function playTone(ctx, start, frequency, duration, gain = 0.28, type = 'sine') {
  const oscillator = ctx.createOscillator();
  const volume = ctx.createGain();
  oscillator.type = type;
  oscillator.frequency.setValueAtTime(frequency, start);
  volume.gain.setValueAtTime(0.0001, start);
  volume.gain.exponentialRampToValueAtTime(gain, start + 0.012);
  volume.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  oscillator.connect(volume);
  volume.connect(ctx.destination);
  oscillator.start(start);
  oscillator.stop(start + duration + 0.02);
}

function playCashRegisterSound() {
  const ctx = getAudioContext();
  if (!ctx) {
    console.warn('AudioContext not supported in this browser');
    return;
  }

  soundUnlocked = true;
  const now = ctx.currentTime + 0.02;

  // Bright cash-register style chime: ding-ding-cha-ching.
  playTone(ctx, now, 987.77, 0.16, 0.30, 'triangle');
  playTone(ctx, now + 0.11, 1318.51, 0.18, 0.30, 'triangle');
  playTone(ctx, now + 0.28, 1760.00, 0.22, 0.34, 'sine');
  playTone(ctx, now + 0.34, 2349.32, 0.18, 0.18, 'triangle');
  playTone(ctx, now + 0.48, 1046.50, 0.28, 0.22, 'sine');

  // Add a tiny register-click/noise burst.
  const bufferSize = Math.floor(ctx.sampleRate * 0.08);
  const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < bufferSize; i++) {
    data[i] = (Math.random() * 2 - 1) * (1 - i / bufferSize) * 0.18;
  }
  const noise = ctx.createBufferSource();
  const noiseGain = ctx.createGain();
  noise.buffer = buffer;
  noiseGain.gain.setValueAtTime(0.001, now + 0.23);
  noiseGain.gain.exponentialRampToValueAtTime(0.16, now + 0.245);
  noiseGain.gain.exponentialRampToValueAtTime(0.001, now + 0.31);
  noise.connect(noiseGain);
  noiseGain.connect(ctx.destination);
  noise.start(now + 0.23);
}

function showSoundToast(message) {
  const existing = document.getElementById('cash-register-sound-toast');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.id = 'cash-register-sound-toast';
  toast.className = 'fixed left-1/2 bottom-24 transform -translate-x-1/2 bg-gray-900 text-white px-4 py-3 rounded-xl shadow-2xl z-[120] font-black text-xs border-2 border-yellow-400';
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 2500);
}

function installSoundTestButton() {
  const apply = () => {
    if (document.getElementById('cash-register-test-button')) return;

    const btn = document.createElement('button');
    btn.id = 'cash-register-test-button';
    btn.type = 'button';
    btn.className = 'fixed right-4 bottom-5 z-[110] rounded-full bg-gradient-to-r from-yellow-400 to-orange-500 text-gray-950 font-black px-4 py-3 shadow-2xl border-2 border-white text-xs active:scale-95';
    btn.textContent = '🔊 Test Sound';
    btn.onclick = () => {
      playCashRegisterSound();
      showSoundToast('Cash register sound is working');
      startOrderSoundPolling();
    };

    document.body.appendChild(btn);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', apply, { once: true });
  } else {
    apply();
  }
}

async function checkForNewOrderSound() {
  try {
    const response = await fetch('/api/orders', { cache: 'no-store' });
    if (!response.ok) return;
    const data = await response.json();
    const orders = Array.isArray(data.orders) ? data.orders : [];
    const currentCount = orders.length;

    if (lastOrderCountForSound === null) {
      lastOrderCountForSound = currentCount;
      return;
    }

    if (currentCount > lastOrderCountForSound) {
      playCashRegisterSound();
      setTimeout(playCashRegisterSound, 650);
      showSoundToast('💰 New order received');
    }

    lastOrderCountForSound = currentCount;
  } catch (error) {
    console.warn('Order sound check failed:', error);
  }
}

function startOrderSoundPolling() {
  if (orderSoundPollStarted) return;
  orderSoundPollStarted = true;
  checkForNewOrderSound();
  setInterval(checkForNewOrderSound, 5000);
}

// Add Marcus profile image to the live dashboard header without changing index.html structure.
function installDashboardProfileAvatar() {
  const apply = () => {
    try {
      if (document.getElementById('dashboard-profile-avatar')) return;

      const headerRight = document.querySelector('header .flex.items-center.gap-1');
      if (!headerRight) return;

      const avatarWrap = document.createElement('div');
      avatarWrap.id = 'dashboard-profile-avatar';
      avatarWrap.className = 'flex items-center gap-1 bg-white px-1.5 py-1 rounded-lg border border-indigo-200 shadow-sm';
      avatarWrap.innerHTML = `
        <img
          src="/assets/jr.jpg"
          alt="Marcus Hawkins"
          class="w-7 h-7 rounded-full object-cover object-top border-2 border-indigo-500"
          loading="eager"
        />
        <div class="hidden sm:block leading-tight pr-1">
          <div class="text-[9px] font-black text-gray-800">Marcus</div>
          <div class="text-[7px] font-bold text-gray-500">Owner</div>
        </div>
      `;

      headerRight.insertBefore(avatarWrap, headerRight.firstChild);
    } catch (error) {
      console.warn('Dashboard profile avatar failed:', error);
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', apply, { once: true });
  } else {
    apply();
  }
}

installDashboardProfileAvatar();
installSoundTestButton();
window.playFulfillmentProCashRegisterSound = playCashRegisterSound;

export async function requestNotificationPermission() {
  try {
    console.log('🔔 Requesting notification permission...');
    playCashRegisterSound();
    startOrderSoundPolling();
    
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
  playCashRegisterSound();
  showSoundToast('💰 New notification received');
  
  const notificationTitle = payload.notification?.title || 'FulfillmentPro';
  const notificationOptions = {
    body: payload.notification?.body || 'New notification',
    icon: '/assets/jr.jpg',
    badge: '/assets/jr.jpg',
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
  banner.textContent = '✅ Push notifications enabled! Cash register sound is active.';
  document.body.appendChild(banner);
  setTimeout(() => banner.remove(), 3000);
}

function showNotificationDenied() {
  const banner = document.createElement('div');
  banner.className = 'fixed top-4 left-1/2 transform -translate-x-1/2 bg-red-500 text-white px-6 py-3 rounded-xl shadow-lg z-50 font-bold text-sm';
  banner.textContent = '🚫 Notifications blocked. Sound test still works in this tab.';
  document.body.appendChild(banner);
  setTimeout(() => banner.remove(), 5000);
}

export { messaging };
