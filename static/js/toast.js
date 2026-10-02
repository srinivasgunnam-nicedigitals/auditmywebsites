function showToast(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        // Check if Tailwind is present by checking for a known tailwind class or just checking if 'landing' page
        const isLanding = document.documentElement.classList.contains('scroll-smooth') || document.querySelector('script[src*="tailwind"]');

        if (isLanding) {
            container.className = 'fixed top-8 right-8 z-[200] flex flex-col gap-4 pointer-events-none';
        } else {
            // Standard CSS container
            // Styles are defined in styles.css
        }
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    const isLanding = document.documentElement.classList.contains('scroll-smooth') || document.querySelector('script[src*="tailwind"]');

    if (isLanding) {
        const colorClasses = {
            success: 'bg-emerald-950/90 border-emerald-500/30 text-emerald-400',
            error: 'bg-slate-900/95 border-red-500/30 text-red-400',
            warning: 'bg-amber-950/90 border-amber-500/30 text-amber-400',
            info: 'bg-blue-950/90 border-blue-500/30 text-blue-400'
        };

        toast.className = `min-w-[320px] max-w-md p-4 rounded-xl border backdrop-blur-md shadow-2xl flex items-center justify-between gap-4 transition-all duration-500 translate-x-12 opacity-0 pointer-events-auto ${colorClasses[type] || colorClasses.info}`;

        const icon = type === 'success' ? 'check-circle' : (type === 'error' ? 'alert-circle' : (type === 'warning' ? 'alert-triangle' : 'info'));

        // Check if Lucide is loaded
        const hasLucide = typeof lucide !== 'undefined';

        // Handle object/array messages (for better error display of API responses)
        let displayMessage = message;
        if (typeof message === 'object' && message !== null) {
            if (Array.isArray(message)) {
                // If it's a FastAPI validation error detail array
                displayMessage = message.map(err => err.msg || JSON.stringify(err)).join(', ');
            } else {
                displayMessage = message.detail || message.message || message.msg || JSON.stringify(message);
            }
        }

        toast.innerHTML = `
            <div class="flex items-center gap-3">
                ${hasLucide ? `<i data-lucide="${icon}" class="w-5 h-5 flex-shrink-0"></i>` : ''}
                <div class="text-sm font-medium tracking-wide">${displayMessage}</div>
            </div>
            <button class="text-slate-500 hover:text-white transition-colors text-xl leading-none">&times;</button>
        `;

        if (hasLucide) setTimeout(() => lucide.createIcons(), 10);
    } else {
        // Use styles.css classes
        toast.className = `toast toast-${type}`;
        const icons = {
            success: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="#10B981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 5L8 14L3 9"/></svg>',
            error: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="#EF4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="10" r="8"/><path d="M12 8L8 12M8 8L12 12"/></svg>',
            warning: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="#F59E0B" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3L1 17h18L10 3zM10 10v3M10 16h.01"/></svg>',
            info: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="#4F7CFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="10" r="8"/><path d="M10 14V10M10 6h.01"/></svg>'
        };

        // Handle object/array messages
        let displayMessage = message;
        if (typeof message === 'object' && message !== null) {
            if (Array.isArray(message)) {
                displayMessage = message.map(err => err.msg || JSON.stringify(err)).join(', ');
            } else {
                displayMessage = message.detail || message.message || message.msg || JSON.stringify(message);
            }
        }

        toast.innerHTML = `
            <div class="toast-icon">${icons[type] || icons.info}</div>
            <div class="toast-content">${displayMessage}</div>
            <div class="toast-close">×</div>
        `;

        toast.querySelector('.toast-close').addEventListener('click', () => removeToast());
    }

    container.appendChild(toast);

    // Trigger animation for landing
    if (isLanding) {
        setTimeout(() => {
            toast.classList.remove('translate-x-12', 'opacity-0');
        }, 10);
        toast.querySelector('button').onclick = () => removeToast();
    }

    const removeToast = () => {
        if (isLanding) {
            toast.classList.add('translate-x-12', 'opacity-0');
            setTimeout(() => toast.remove(), 500);
        } else {
            toast.classList.add('toast-closing');
            toast.addEventListener('animationend', () => {
                toast.remove();
                if (container.childNodes.length === 0) container.remove();
            }, { once: true });
        }
    };

    // Auto-close after 5 seconds
    setTimeout(removeToast, 5000);
}

// Global exposure
window.showToast = showToast;
