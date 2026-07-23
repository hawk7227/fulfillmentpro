(function(){
'use strict';
function addDesktopNavigation(){
  const sidebar=document.querySelector('.sidebar .nav');
  if(sidebar&&!sidebar.querySelector('[data-desktop-ops]')){
    const links=[
      ['Orders','/orders.html','🛒'],
      ['Fulfillment Queue','/queue.html','📦'],
      ['Product Mapping','/mapping.html','🔗'],
      ['Notifications','/notifications.html','🔔']
    ];
    const section=document.createElement('div');
    section.dataset.desktopOps='true';
    section.className='desktop-ops-links';
    section.innerHTML='<div class="desktop-ops-title">Operations pages</div>'+links.map(([label,href,icon])=>'<a href="'+href+'"><span>'+icon+'</span><b>'+label+'</b><small>Open →</small></a>').join('');
    sidebar.appendChild(section);
  }

  const main=document.querySelector('.main');
  const heading=document.querySelector('.heading-row');
  if(main&&heading&&!document.querySelector('.desktop-ops-grid')){
    const grid=document.createElement('section');
    grid.className='desktop-ops-grid';
    grid.setAttribute('aria-label','Fulfillment operations pages');
    grid.innerHTML=[
      ['Orders','Live Shopify orders, customer totals, payment and fulfillment status.','/orders.html','🛒'],
      ['Queue','Current worker activity, waiting orders, verification and failures.','/queue.html','📦'],
      ['Mapping','Products and order lines that require supplier mapping.','/mapping.html','🔗'],
      ['Notifications','New orders, fulfillment results, failures, verification and worker alerts.','/notifications.html','🔔']
    ].map(([title,copy,href,icon])=>'<a href="'+href+'"><span>'+icon+'</span><div><b>'+title+'</b><small>'+copy+'</small></div><em>Open</em></a>').join('');
    heading.insertAdjacentElement('afterend',grid);
  }
}

function refreshDashboardForNewOrder(){
  const refresh=document.getElementById('refreshBtn');
  if(refresh) refresh.click();
}

window.addEventListener('fulfillmentpro:new-order',refreshDashboardForNewOrder);
document.addEventListener('DOMContentLoaded',addDesktopNavigation);
if(document.readyState!=='loading')addDesktopNavigation();
})();
