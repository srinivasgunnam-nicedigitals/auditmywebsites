// --- Sidebar Collapsible Logic & Persistence ---
function saveSidebarState() {
    const openSections = [];
    document.querySelectorAll('.nav-section-title.collapsible').forEach(el => {
        // Check if 'open' class is present on the header
        if (el.classList.contains('open')) {
            const span = el.querySelector('.nav-section-main span');
            if (span) openSections.push(span.textContent.trim());
        }
    });
    console.log('Saving Sidebar State:', openSections);
    localStorage.setItem('sidebarOpenSections', JSON.stringify(openSections));
}

function restoreSidebarState() {
    const stored = localStorage.getItem('sidebarOpenSections');
    console.log('Restoring Sidebar State from:', stored);
    if (stored === null) return;

    try {
        const openSections = JSON.parse(stored);
        document.querySelectorAll('.nav-section-title.collapsible').forEach(el => {
            const span = el.querySelector('.nav-section-main span');
            if (!span) return;
            const text = span.textContent.trim();
            const submenu = el.nextElementSibling;

            if (openSections.includes(text)) {
                console.log('Opening section:', text);
                el.classList.add('open');
                if (submenu && submenu.classList.contains('nav-submenu')) {
                    submenu.classList.add('open');
                    submenu.style.maxHeight = '500px'; // Force height just in case CSS transition fails
                    submenu.style.opacity = '1';
                }
            } else {
                // Only close if it's not the active page's default?
                // Actually, persistence should override default.
                // So if it's NOT in openSections, we force close it.
                // UNLESS the user navigates to a page where it SHOULD be open by context and they haven't explicitly closed it?
                // The current logic assumes strict persistence: what you leave as, is what you get.
                el.classList.remove('open');
                if (submenu && submenu.classList.contains('nav-submenu')) {
                    submenu.classList.remove('open');
                    submenu.style.maxHeight = '0';
                    submenu.style.opacity = '0';
                }
            }
        });
    } catch (e) {
        console.error('Failed to restore sidebar state:', e);
    }
}

// Call restore immediately
restoreSidebarState();

function highlightSidebarByPath() {
    const path = window.location.pathname;
    const search = window.location.search;
    console.log('Highlighting Sidebar for:', path, search);

    // Remove active class from all items
    document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));

    let targetItem = null;

    // Define mapping of paths to sidebar links
    const mappings = [
        { pattern: /^\/platform\/dashboard/, selector: 'a[href="/platform/dashboard"]' },

        // Audit Tools (Scan/Input pages)
        { pattern: /^\/scan\/xml-sitemaps/, selector: 'a[href="/scan/xml-sitemaps"]' },
        { pattern: /^\/phone-audit/, selector: 'a[href="/phone-audit"]' },
        { pattern: /^\/h1-audit/, selector: 'a[href="/h1-audit"]' },
        { pattern: /^\/scan\/meta-tags/, selector: 'a[href="/scan/meta-tags"]' },
        { pattern: /^\/platform\/image-alt/, selector: 'a[href="/platform/image-alt"]' },
        { pattern: /^\/platform\/device-lab/, selector: 'a[href="/platform/device-lab"]' },
        { pattern: /^\/platform\/static/, selector: 'a[href="/platform/static"]' },
        { pattern: /^\/platform\/performance/, selector: 'a[href="/platform/performance"]' },
        { pattern: /^\/platform\/accessibility/, selector: 'a[href="/platform/accessibility"]' },

        // Results -> Audit History mapping
        { pattern: /^\/results\/sitemap/, selector: 'a[href="/platform/history?type=sitemap"]' },
        { pattern: /^\/results\/phone/, selector: 'a[href="/platform/history?type=phone"]' },
        { pattern: /^\/results\/h1/, selector: 'a[href="/platform/history?type=h1"]' },
        { pattern: /^\/results\/meta-tags/, selector: 'a[href="/platform/history?type=meta-tags"]' },
        { pattern: /^\/results\/image-alt/, selector: 'a[href="/platform/history?type=image-alt"]' },
        { pattern: /^\/results\/static/, selector: 'a[href="/platform/history?type=static"]' },
        { pattern: /^\/results\/performance/, selector: 'a[href="/platform/history?type=performance"]' },
        { pattern: /^\/results\/accessibility/, selector: 'a[href="/platform/history?type=accessibility"]' },

        // History filters
        { pattern: /^\/platform\/history/, selector: 'a[href^="/platform/history"]', matchQuery: true },

        { pattern: /^\/platform\/settings/, selector: 'a[href="/platform/settings"]' }
    ];

    for (const mapping of mappings) {
        if (mapping.pattern.test(path)) {
            if (mapping.matchQuery && search) {
                // Parse URL parameters to extract 'type'
                const urlParams = new URLSearchParams(search);
                const typeParam = urlParams.get('type');

                if (typeParam && typeParam !== 'all') {
                    const exactMatch = document.querySelector(`a[href="/platform/history?type=${typeParam}"]`);
                    if (exactMatch) {
                        targetItem = exactMatch;
                        break;
                    }
                } else {
                    const allAuditsMatch = document.querySelector(`a[href="/platform/history"]`);
                    if (allAuditsMatch) {
                        targetItem = allAuditsMatch;
                        break;
                    }
                }
            }
            targetItem = document.querySelector(mapping.selector);
            if (targetItem) break;
        }
    }

    if (targetItem) {
        targetItem.classList.add('active');

        // Ensure parent section is open
        const submenu = targetItem.closest('.nav-submenu');
        if (submenu) {
            const header = submenu.previousElementSibling;
            if (header && header.classList.contains('nav-section-title') && header.classList.contains('collapsible')) {
                // Enforce accordion: Close all OTHER open submenus
                document.querySelectorAll('.nav-section-title.collapsible.open').forEach(openHeader => {
                    if (openHeader !== header) {
                        openHeader.classList.remove('open');
                        const openSubmenu = openHeader.nextElementSibling;
                        if (openSubmenu && openSubmenu.classList.contains('nav-submenu')) {
                            openSubmenu.classList.remove('open');
                            openSubmenu.style.maxHeight = '0';
                            openSubmenu.style.opacity = '0';
                        }
                    }
                });

                if (!header.classList.contains('open')) {
                    header.classList.add('open');
                    submenu.classList.add('open');
                    submenu.style.maxHeight = '500px';
                    submenu.style.opacity = '1';
                    saveSidebarState();
                }
            }
        }
    }
}

// --- Global Click Handlers (Delegation) ---
document.addEventListener('click', (e) => {
    // 1. Sidebar Collapsible Toggle
    const header = e.target.closest('.nav-section-title.collapsible');
    if (header) {
        const submenu = header.nextElementSibling;
        if (submenu && submenu.classList.contains('nav-submenu')) {
            // ACCORDION LOGIC: Close all OTHER open submenus
            document.querySelectorAll('.nav-section-title.collapsible.open').forEach(openHeader => {
                if (openHeader !== header) {
                    openHeader.classList.remove('open');
                    const openSubmenu = openHeader.nextElementSibling;
                    if (openSubmenu && openSubmenu.classList.contains('nav-submenu')) {
                        openSubmenu.classList.remove('open');
                        openSubmenu.style.maxHeight = '0';
                        openSubmenu.style.opacity = '0';
                    }
                }
            });

            // Toggle logic for the CLICKED submenu
            const isOpen = header.classList.toggle('open');
            submenu.classList.toggle('open');

            if (isOpen) {
                submenu.style.maxHeight = '500px';
                submenu.style.opacity = '1';
            } else {
                submenu.style.maxHeight = '0';
                submenu.style.opacity = '0';
            }
            saveSidebarState();
        }
        return;
    }

    // 2. View History Buttons
    const historyBtn = e.target.closest('.view-history-btn');
    if (historyBtn) {
        const type = historyBtn.dataset.type;
        if (type) {
            window.location.href = `/platform/history?type=${type}`;
        }
        return;
    }

    // 3. Close Multiselect Dropdowns Click Outside
    const isMultiselectClick = e.target.closest('.custom-multiselect') || e.target.closest('.tags-input');
    if (!isMultiselectClick) {
        document.querySelectorAll('.dropdown-menu.show').forEach(menu => {
            menu.classList.remove('show');
        });
    }
});

// Use Delegation for Sidebar Toggles (handled above)

document.addEventListener('DOMContentLoaded', () => {
    // Highlight sidebar based on current URL
    highlightSidebarByPath();

    // --- State Management ---
    let currentSessionId = null;
    let pollInterval = null;
    let currentAuditUrlCount = 0;

    // --- Sidebar Collapsible Logic ---
    // --- Helper: Get Current Audit Type ---
    function getAuditType() {
        const path = window.location.pathname;
        if (path.includes('/platform/dashboard')) return 'static';
        if (path.includes('/platform/static')) return 'static';
        if (path.includes('/platform/performance')) return 'performance';
        if (path.includes('/platform/accessibility')) return 'accessibility';
        if (path.includes('/platform/h1') || path.includes('/h1-audit')) return 'h1';
        if (path.includes('/platform/sitemap') || path.includes('/scan/xml-sitemaps')) return 'sitemap';
        if (path.includes('/platform/meta-tags') || path.includes('/scan/meta-tags')) return 'meta-tags';
        if (path.includes('/platform/image-alt')) return 'image-alt';
        if (path.includes('/phone-audit')) return 'phone';

        // Final fallback based on specific keywords in path
        if (path.includes('h1')) return 'h1';
        if (path.includes('sitemap')) return 'sitemap';
        if (path.includes('meta')) return 'meta-tags';

        return 'static'; // Default
    }

    // --- File Upload Drag & Drop ---
    const dropZone = document.getElementById('drop-zone');
    if (dropZone) {
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, e => {
                e.preventDefault();
                e.stopPropagation();
            }, false);
        });

        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => {
                dropZone.style.borderColor = '#4F46E5';
                dropZone.style.backgroundColor = 'rgba(79, 70, 229, 0.05)';
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => {
                dropZone.style.borderColor = '#2D3748';
                dropZone.style.backgroundColor = 'rgba(31, 41, 55, 0.4)';
            }, false);
        });

        dropZone.addEventListener('drop', e => {
            const files = e.dataTransfer.files;
            handleFiles(files);
        }, false);

        dropZone.addEventListener('click', () => {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = '.txt';
            input.onchange = e => handleFiles(e.target.files);
            input.click();
        });

        async function handleFiles(files) {
            if (files.length > 0) {
                const file = files[0];
                const text = await file.text();
                // Store file content in a hidden attribute or a global variable
                dropZone.dataset.fileContent = text;

                // Change the SVG icon to a file-uploaded checkmark icon
                const iconEl = dropZone.querySelector('img');
                if (iconEl) {
                    iconEl.outerHTML = `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#00C48C" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="upload-success-icon">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                        <polyline points="14 2 14 8 20 8"></polyline>
                        <polyline points="9 15 11 17 15 13"></polyline>
                    </svg>`;
                }

                // Update the text to show filename
                const uploadText = dropZone.querySelector('.upload-text');
                if (uploadText) {
                    uploadText.textContent = file.name;
                    uploadText.style.color = '#00C48C';
                    uploadText.style.fontWeight = '500';
                }

                // Add a success border style to the drop zone
                dropZone.style.borderColor = '#00C48C';
                dropZone.style.backgroundColor = 'rgba(0, 196, 140, 0.05)';

                // Show a toast notification
                if (typeof showToast === 'function') {
                    showToast(`File "${file.name}" uploaded successfully`, 'success');
                }
            }
        }
    }

    // --- Start Audit Logic ---
    const startBtn = document.querySelector('.btn-primary');
    const auditModal = document.getElementById('audit-modal') || document.getElementById('progress-modal');

    // Modal Elements
    const stopBtn = document.querySelector('.stop-session-btn') || document.getElementById('stop-btn');
    const closeBtn = document.querySelector('.modal-close') || document.getElementById('close-modal');
    const viewReportBtn = document.querySelector('.view-report-btn') || document.getElementById('view-report-btn');
    const progressBar = document.querySelector('.audit-progress-bar') || document.getElementById('progress-bar');
    const progressContainer = document.querySelector('.audit-progress-container');
    const progressText = document.querySelector('.audit-progress-text') || document.getElementById('progress-text');
    const processedCount = document.getElementById('processed-url-count') || document.getElementById('progress-status');
    const subtitle = document.querySelector('.modal-subtitle');

    // --- Checkbox Group Logic ---
    document.querySelectorAll('.checkbox-group-container').forEach(container => {
        const selectAll = container.querySelector('.select-all-checkbox');
        if (!selectAll) return;

        const checkboxes = container.querySelectorAll('input[type="checkbox"]:not(.select-all-checkbox)');

        // Select All -> All
        selectAll.addEventListener('change', () => {
            checkboxes.forEach(cb => cb.checked = selectAll.checked);
        });

        // Individual -> Select All state
        checkboxes.forEach(cb => {
            cb.addEventListener('change', () => {
                const allChecked = Array.from(checkboxes).every(c => c.checked);
                selectAll.checked = allChecked;
            });
        });
    });

    async function startAudit() {
        const type = getAuditType();

        // Find project name more reliably
        const projectNameInput = document.querySelector('[name="session_name"]') || document.querySelector('.form-input');
        const projectName = projectNameInput ? projectNameInput.value.trim() : "";

        // Helper to Highlight Error
        const highlightError = (input, message = 'Enter correct url') => {
            if (!input) return;
            input.focus();
            input.style.borderColor = '#EF4444';

            // Show inline text
            let errorMsg = input.nextElementSibling;
            if (!errorMsg || !errorMsg.classList.contains('input-error-msg')) {
                errorMsg = document.createElement('div');
                errorMsg.className = 'input-error-msg';
                errorMsg.style.color = '#EF4444';
                errorMsg.style.fontSize = '0.85rem';
                errorMsg.style.marginTop = '0.25rem';
                errorMsg.textContent = message;
                if (input.parentNode) input.parentNode.insertBefore(errorMsg, input.nextSibling);
            } else {
                errorMsg.textContent = message;
            }

            input.addEventListener('input', () => {
                input.style.borderColor = '';
                if (errorMsg && errorMsg.parentNode) {
                    errorMsg.remove();
                }
            }, { once: true });
        };

        if (!projectName || projectName.toLowerCase() === 'select') {
            if (projectNameInput) {
                highlightError(projectNameInput, 'Enter Project Name');
            }
            return;
        }

        // Collect URLs
        // Prefer [name="manual_urls"] over .form-textarea to avoid picking up other inputs
        const textarea = document.querySelector('[name="manual_urls"]') || document.querySelector('.form-textarea:not([name="target_numbers"])');
        const singleUrlInput = document.querySelector('[name="url"]');
        const liveInput = document.querySelector('[name="live_url"]');
        const stagingInput = document.querySelector('[name="staging_url"]');
        const crawlInput = document.querySelector('[name="crawl_url"]');
        const isCrawlSite = document.querySelector('[name="crawl_site"]:checked') !== null;

        let urls = [];
        if (textarea) {
            urls = textarea.value.split('\n').filter(u => u.trim());
        } else if (singleUrlInput) {
            urls = [singleUrlInput.value.trim()].filter(u => u);
        }

        // Add Live/Staging URLs if present
        if (liveInput && liveInput.value.trim()) urls.push(liveInput.value.trim());
        if (stagingInput && stagingInput.value.trim()) urls.push(stagingInput.value.trim());
        if (crawlInput && crawlInput.value.trim()) urls.push(crawlInput.value.trim());

        if (dropZone && dropZone.dataset.fileContent) {
            const fileUrls = dropZone.dataset.fileContent.split('\n').filter(u => u.trim());
            urls = [...urls, ...fileUrls];
        }

        if (urls.length === 0) {
            if (type === 'sitemap') {
                if (singleUrlInput) highlightError(singleUrlInput, 'Enter Page URL');
                showToast('Please provide a URL to scan', 'error');
            } else {
                await window.showAlert('URLs Required', 'Please provide at least one URL before starting the audit.');
                if (textarea) highlightError(textarea, 'Enter correct url');
                else if (singleUrlInput) highlightError(singleUrlInput, 'Enter correct url');
                else if (liveInput) highlightError(liveInput, 'Enter correct url');
            }
            return;
        }

        // Image Alt & Meta Tags explicitly require either comparison URLs OR manual URLs
        if (type === 'image-alt' || type === 'meta-tags') {
            const hasManual = urls.length > 0 && !liveInput && !stagingInput; // If we only have textarea
            const hasLive = liveInput && liveInput.value.trim() !== '';
            const hasStaging = stagingInput && stagingInput.value.trim() !== '';
            
            // If manual URLs are provided via textarea (which 'urls' would contain if parsed)
            const manualTextarea = document.querySelector('[name="manual_urls"]');
            const manualUrlsCount = manualTextarea ? manualTextarea.value.split('\n').filter(u => u.trim()).length : 0;

            if (manualUrlsCount === 0 && (!hasLive || !hasStaging)) {
                if (!hasLive && liveInput) highlightError(liveInput, 'Enter Live Site URL');
                if (!hasStaging && stagingInput) highlightError(stagingInput, 'Enter Staging Site URL');
                showToast('Please enter URLs for comparison or manual audit', 'error');
                return;
            }
        }

        // Validate URLs
        const isValidUrl = (string) => {
            // Accept www. prefix (strict check as requested)
            if (/^www\./i.test(string)) return true;
            try {
                const url = new URL(string);
                return url.protocol === "http:" || url.protocol === "https:";
            } catch (_) {
                return false;
            }
        };

        const normalizeUrl = (string) => {
            if (/^www\./i.test(string)) return 'https://' + string;
            return string;
        };

        // Validate and Highlight Specific Inputs
        const validateInput = (input) => {
            if (!input) return true;
            const value = input.value.trim();
            if (!value) return true;

            // Textarea handling
            if (input === textarea) {
                const lines = value.split('\n').filter(l => l.trim());
                for (const line of lines) {
                    if (!isValidUrl(line)) {
                        highlightError(input);
                        // Also show toast as per previous logic
                        showToast('Please enter a correct URL (including http:// or https://)', 'error');
                        return false;
                    }
                }
                return true;
            }

            // Single Input handling
            if (!isValidUrl(value)) {
                highlightError(input);
                showToast('Please enter a correct URL (including http:// or https://)', 'error');
                return false;
            }
            return true;
        };

        // Check textarea if exists
        if (textarea && !validateInput(textarea)) return;

        // Check singleUrlInput if exists
        if (singleUrlInput && !validateInput(singleUrlInput)) return;

        // Check liveInput if exists
        if (liveInput && !validateInput(liveInput)) return;

        // Check stagingInput if exists
        if (stagingInput && !validateInput(stagingInput)) return;

        // Check textarea if exists
        if (textarea && !validateInput(textarea)) return;

        // Check singleUrlInput if exists
        if (singleUrlInput && !validateInput(singleUrlInput)) return;

        // Check liveInput if exists
        if (liveInput && !validateInput(liveInput)) return;

        // Check stagingInput if exists
        if (stagingInput && !validateInput(stagingInput)) return;

        // Check crawlInput if exists
        if (crawlInput && !validateInput(crawlInput)) return;

        // Collect Multi-selects
        const getSelected = (id) => {
            const container = document.getElementById(id);
            if (!container) return [];

            // Check for new checkbox structure
            const checkedInputs = Array.from(container.querySelectorAll('input[type="checkbox"]:checked'));
            if (checkedInputs.length > 0 || container.querySelector('input[type="checkbox"]')) {
                return checkedInputs.map(input => input.value).filter(v => v !== 'all');
            }

            // Fallback to old tag structure
            return Array.from(container.querySelectorAll('.tag')).map(t => t.dataset.value);
        };
        const browsers = getSelected('browser-multiselect');
        const resolutions = getSelected('resolution-multiselect');
        const options = getSelected('options-multiselect');

        // Form Payload
        // Create FormData payload instead of JSON
        const formData = new FormData();
        formData.append('session_name', projectName);

        // Normalize URLs for submission
        const normalizedUrls = urls.map(normalizeUrl);

        // Combine all URLs (manual + file) into one string for manual_urls field
        // This is easier than handling the File object since we already parsed it
        if (normalizedUrls.length > 0) {
            formData.append('manual_urls', normalizedUrls.join('\n'));
        }

        // Explicitly append live/staging fields for Meta comparison
        if ((type === 'meta-tags' || type === 'image-alt') && liveInput && stagingInput) {
            formData.append('live_url', normalizeUrl(liveInput.value.trim()));
            formData.append('staging_url', normalizeUrl(stagingInput.value.trim()));
        }

        if (type === 'image-alt' && isCrawlSite) {
            formData.append('crawl_site', 'true');
        }

        if (isCrawlSite) {
            formData.append('crawl_site', 'true');
        }

        if (crawlInput && crawlInput.value.trim()) {
            formData.append('crawl_url', normalizeUrl(crawlInput.value.trim()));
        }

        let endpoint = `/upload/${type}`;

        if (type === 'static') {
            if (browsers.length === 0) {
                await window.showAlert('Browser Required', 'Please select at least one browser.');
                return;
            }
            if (resolutions.length === 0) {
                await window.showAlert('Resolution Required', 'Please select at least one resolution.');
                return;
            }
            formData.append('browsers', JSON.stringify(browsers));
            formData.append('resolutions', JSON.stringify(resolutions));
        } else if (type === 'performance') {
            const activeEnvs = Array.from(document.querySelectorAll('.env-option.active'));
            const strategies = activeEnvs.length > 0 ? activeEnvs.map(opt => opt.dataset.env) : ['desktop'];
            formData.append('strategies', JSON.stringify(strategies));
        } else if (type === 'dynamic') {
            const browserList = browsers.length ? browsers : ['Chrome'];
            const resList = resolutions.length ? resolutions : ['1920x1080'];
            formData.append('browsers', JSON.stringify(browserList));
            formData.append('resolutions', JSON.stringify(resList));
        } else if (type === 'phone') {
            // Options are now hardcoded for better user experience
            formData.append('target_numbers', '');
            formData.append('options', JSON.stringify(['format', 'links', 'schema']));
        }
        else if (type === 'h1') {
            // No extra fields needed
        } else if (type === 'meta-tags') {
            // No extra fields needed
        } else if (type === 'sitemap') {
            // Sitemap likely takes a single URL as 'url' query param or form?
            // Checking main.py: audit_sitemap_logic takes 'url'.
            // I'd better check main.py for /upload/sitemap or similar.
            // But assuming basic fix for now.
            formData.append('url', normalizeUrl(urls[0]));
            endpoint = '/upload/sitemap';
        }

        // Debug
        // for (var pair of formData.entries()) {
        //     console.log(pair[0]+ ', ' + pair[1]); 
        // }

        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                // Content-Type header is NOT set to allow browser to set boundary
                body: formData
            });

            if (!response.ok) {
                const errorData = await response.json();
                if (response.status === 403 || (errorData.error && errorData.error.toLowerCase().includes('credits'))) {
                    window.showAlert('Credits Exhausted', 'Your credits are finished. Please top up to continue.');
                } else {
                    showToast(errorData.error || 'Failed to start audit', 'error');
                }
                return;
            }
            const data = await response.json();

            // Low Credit Popup logic
            if (data.low_credits) {
                window.showAlert('Low Credits Warning', 'Your credit balance is low (50 or below). Please top up soon to avoid interruption.');
            }

            // Backend returns 'session' for static/dynamic/h1/phone, but checks might vary.
            // Using fallback to be safe.
            currentSessionId = data.session || data.session_id;
            currentAuditUrlCount = normalizedUrls.length;

            // Calculate expected total for immediate UI feedback
            let expectedTotal = 0;
            if (type === 'static') {
                expectedTotal = urls.length * browsers.length * resolutions.length;
            } else if (type === 'meta-tags' && isCrawlSite) {
                expectedTotal = 1; // Will be updated by backend during crawl
            } else {
                expectedTotal = urls.length;
            }

            // Show Modal & Start Polling
            if (auditModal) auditModal.style.display = 'flex';
            resetModalUI();
            startPolling(type, currentSessionId);
        } catch (err) {
            showToast(err.message, 'error');
        }
    }

    function resetModalUI() {
        if (progressBar) {
            progressBar.style.width = '0%';
            progressBar.classList.remove('success');
        }
        if (progressContainer) progressContainer.classList.remove('success');
        if (progressText) progressText.textContent = '0%';

        // Hide status text initially
        const statusElement = document.querySelector('.progress-status');
        if (statusElement) statusElement.style.visibility = 'hidden';

        if (stopBtn) stopBtn.style.display = 'inline-flex';
        if (viewReportBtn) viewReportBtn.style.display = 'none';
        if (subtitle) subtitle.textContent = 'Audit is running in the background...';
    }

    function startPolling(type, sessionId) {
        if (pollInterval) clearInterval(pollInterval);
        pollInterval = setInterval(async () => {
            try {
                const response = await fetch(`/progress/${type}/${sessionId}`);
                if (!response.ok) return;
                const data = await response.json();

                const total = data.total || data.total_expected || 1; // Fallback to 1 to avoid div by zero
                const percent = Math.min(100, Math.floor((data.completed / total) * 100)) || 0;
                
                // Define these early for use in all status blocks
                const processedSpan = document.getElementById('processed-url-count');
                const totalSpan = document.getElementById('total-url-count');
                const statusElement = document.querySelector('.progress-status');

                if (data.status && data.status.startsWith('crawling:')) {
                    // Crawling Phase
                    const currentUrl = data.status.split('crawling:')[1];
                    if (subtitle) subtitle.textContent = `Crawling: ${currentUrl}`;
                    // Show indeterminate or just count
                    if (progressBar) {
                        progressBar.style.width = '100%';
                        progressBar.classList.add('indeterminate'); // Optional: Add CSS for striped animation if desired
                    }
                    if (progressText) progressText.textContent = `Found ${data.completed} pages`;

                    if (processedSpan && totalSpan) {
                        processedSpan.textContent = data.completed;
                        totalSpan.textContent = "???";
                    }
                } else {
                    if (subtitle && !subtitle.textContent.includes('completed')) {
                        subtitle.textContent = 'Audit is running in the background...';
                    }
                    if (progressBar) progressBar.classList.remove('indeterminate');

                    if (progressBar) progressBar.style.width = `${percent}%`;
                    if (progressText) progressText.textContent = `${percent}%`;

                    // Update UI visibility
                    if (statusElement) statusElement.style.visibility = 'visible';

                    if (processedSpan && totalSpan) {
                        processedSpan.textContent = data.completed;
                        totalSpan.textContent = total;
                    } else if (processedCount) {
                        // Fallback for other layouts (phone, generic) if they differ
                        processedCount.textContent = `Processed ${data.completed} of ${total}`;
                    }
                }

                if (data.status === 'completed' || (percent >= 100 && data.status && !data.status.startsWith('crawling') && data.status !== 'running')) {
                    clearInterval(pollInterval);
                    onAuditComplete(type, sessionId);
                } else if (data.status === 'error') {
                    clearInterval(pollInterval);
                    showToast('An error occurred during the audit.', 'error');
                    if (auditModal) auditModal.style.display = 'none';
                } else if (data.status && data.status.includes('credits exhausted')) {
                    clearInterval(pollInterval);
                    if (auditModal) auditModal.style.display = 'none';
                    window.showAlert('Credits Exhausted', 'Your credits are finished. Please top up to continue.');
                }
            } catch (err) {
                console.error('Polling error:', err);
            }
        }, 2000);
    }

    function onAuditComplete(type, sessionId) {
        if (progressBar) {
            progressBar.style.width = '100%';
            progressBar.classList.add('success');
        }
        if (progressContainer) progressContainer.classList.add('success');
        if (progressText) progressText.textContent = '100%';
        if (stopBtn) stopBtn.style.display = 'none';
        if (viewReportBtn) {
            viewReportBtn.style.display = 'inline-block';
            viewReportBtn.href = `/results/${type}/${sessionId}`;
        }
        if (subtitle) subtitle.textContent = 'Audit completed successfully!';

        // Change "Processing URL X of Y" → "Processed X URLs"
        const statusElement = document.querySelector('.progress-status');
        if (statusElement) {
            const totalSpan = document.getElementById('total-url-count');
            const totalTasks = totalSpan ? totalSpan.textContent : '';
            
            if (type === 'static' || type === 'dynamic') {
                statusElement.innerHTML = `Processed <strong>${currentAuditUrlCount}</strong> URL${currentAuditUrlCount == 1 ? '' : 's'} (${totalTasks} screenshots)`;
            } else {
                statusElement.innerHTML = `Processed <strong>${totalTasks}</strong> URL${totalTasks == 1 ? '' : 's'}`;
            }
        }
    }

    // --- Start Audit Buttons ---
    document.body.addEventListener('click', (e) => {
        const startBtn = e.target.closest('.start-audit-btn') || e.target.closest('.btn-primary');
        if (startBtn && (startBtn.classList.contains('start-audit-btn') || startBtn.textContent.includes('Start'))) {
            startAudit();
        }
    });

    // --- Custom Confirmation Logic ---
    window.showConfirm = function (title, message) {
        return new Promise((resolve) => {
            const modal = document.getElementById('confirm-modal');
            const titleEl = document.getElementById('confirm-title');
            const msgEl = document.getElementById('confirm-message');
            const proceedBtn = document.getElementById('confirm-proceed');
            const cancelBtn = document.getElementById('confirm-cancel');

            if (!modal || !titleEl || !msgEl || !proceedBtn || !cancelBtn) {
                // Fallback to native confirm if modal HTML is missing
                resolve(confirm(message));
                return;
            }

            titleEl.textContent = title;
            msgEl.textContent = message;
            modal.style.display = 'flex';

            const onConfirm = () => {
                cleanup();
                resolve(true);
            };

            const onCancel = () => {
                cleanup();
                resolve(false);
            };

            const cleanup = () => {
                proceedBtn.removeEventListener('click', onConfirm);
                cancelBtn.removeEventListener('click', onCancel);
                modal.style.display = 'none';
            };


            proceedBtn.addEventListener('click', onConfirm);
            cancelBtn.addEventListener('click', onCancel);
        });
    };

    window.showAlert = function (title, message) {
        return new Promise((resolve) => {
            const modal = document.getElementById('confirm-modal');
            const titleEl = document.getElementById('confirm-title');
            const msgEl = document.getElementById('confirm-message');
            const proceedBtn = document.getElementById('confirm-proceed');
            const cancelBtn = document.getElementById('confirm-cancel');

            if (!modal || !titleEl || !msgEl || !proceedBtn || !cancelBtn) {
                alert(message);
                resolve();
                return;
            }

            titleEl.textContent = title;
            msgEl.textContent = message;
            cancelBtn.style.display = 'none'; // Hide cancel for alerts
            modal.style.display = 'flex';

            const onConfirm = () => {
                cancelBtn.style.display = 'block'; // Restore for next use
                proceedBtn.removeEventListener('click', onConfirm);
                modal.style.display = 'none';
                resolve();
            };

            proceedBtn.addEventListener('click', onConfirm);
        });
    };

    // --- Stop & Close Modal ---
    if (stopBtn) {
        stopBtn.addEventListener('click', async () => {
            if (currentSessionId && await window.showConfirm('Stop Session?', 'Are you sure you want to stop this audit session?')) {
                await fetch(`/api/sessions/${currentSessionId}/stop`, { method: 'POST' });
                if (pollInterval) clearInterval(pollInterval);
                if (auditModal) auditModal.style.display = 'none';
            }
        });
    }

    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            if (pollInterval) clearInterval(pollInterval);
            // If on a history page, just reload to stay on the same page
            if (window.location.pathname.includes('/platform/history')) {
                window.location.reload();
                return;
            }
            // Otherwise redirect to audit history
            const type = getAuditType();
            window.location.href = `/platform/history?type=${type}`;
        });
    }


    // --- Environment Selection (Speed Test) ---
    document.body.addEventListener('click', (e) => {
        const option = e.target.closest('.env-option');
        if (option) {
            const type = getAuditType();
            if (type === 'performance') {
                // Toggle for multi-select
                option.classList.toggle('active');

                // Ensure at least one is always selected? 
                // Alternatively, let them unselect all and fallback in startAudit
            } else {
                // Radio behavior for others if any
                document.querySelectorAll('.env-option').forEach(opt => opt.classList.remove('active'));
                option.classList.add('active');
            }
        }
    });

    // --- Sidebar & Profile ---
    const sidebarToggle = document.getElementById('sidebar-toggle');
    const sidebar = document.querySelector('.sidebar');
    const mainContent = document.querySelector('.main-content');

    if (sidebarToggle && sidebar && mainContent) {
        // Restore collapse state on load
        const isCurrentlyCollapsed = localStorage.getItem('sidebarCollapsed') === 'true';
        if (isCurrentlyCollapsed) {
            sidebar.classList.add('collapsed');
            mainContent.classList.add('sidebar-collapsed');
        }

        // --- IMPORTANT: Clear the preload state to reveal labels/logo ---
        document.documentElement.classList.remove('sidebar-collapsed-preload');

        sidebarToggle.addEventListener('click', () => {
            const isCollapsed = sidebar.classList.toggle('collapsed');
            mainContent.classList.toggle('sidebar-collapsed');
            localStorage.setItem('sidebarCollapsed', isCollapsed);
        });

        // --- Mobile Menu Logic ---
        const mobileToggle = document.querySelector('.mobile-menu-toggle');
        const sidebarOverlay = document.querySelector('.sidebar-overlay');

        if (mobileToggle && sidebarOverlay) {
            mobileToggle.addEventListener('click', () => {
                sidebar.classList.toggle('mobile-open');
                sidebarOverlay.classList.toggle('active');
            });

            sidebarOverlay.addEventListener('click', () => {
                sidebar.classList.remove('mobile-open');
                sidebarOverlay.classList.remove('active');
            });

            // Auto-close on link click (mobile/tablet)
            sidebar.querySelectorAll('.nav-item').forEach(link => {
                link.addEventListener('click', () => {
                    if (window.innerWidth <= 1024) {
                        sidebar.classList.remove('mobile-open');
                        sidebarOverlay.classList.remove('active');
                    }
                });
            });
        }

        // Close mobile menu on Esc
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && sidebar.classList.contains('mobile-open')) {
                sidebar.classList.remove('mobile-open');
                if (sidebarOverlay) sidebarOverlay.classList.remove('active');
            }
        });
    }

    // --- Global Multi-select ---
    window.setupMultiSelect = function (containerId, placeholderText) {
        const container = document.getElementById(containerId);
        if (!container) return;
        const tagsDisplay = container.querySelector('.tags-input');
        const dropdown = container.querySelector('.dropdown-menu');
        const options = container.querySelectorAll('.dropdown-option:not(.select-all-option)');
        const selectAllOpt = container.querySelector('.select-all-option');

        tagsDisplay.addEventListener('click', () => dropdown.classList.toggle('show'));

        const updateSelectAllState = () => {
            if (selectAllOpt) {
                const allSelected = Array.from(options).every(opt => opt.classList.contains('selected'));
                selectAllOpt.classList.toggle('selected', allSelected);
                const checkbox = selectAllOpt.querySelector('input[type="checkbox"]');
                if (checkbox) checkbox.checked = allSelected;
            }
        };

        const toggleOption = (opt, forceState) => {
            const val = opt.dataset.value;
            const text = opt.textContent;
            const currentlySelected = opt.classList.contains('selected');
            const targetState = forceState !== undefined ? forceState : !currentlySelected;

            if (targetState && !currentlySelected) {
                opt.classList.add('selected');
                const tag = document.createElement('div');
                tag.className = 'tag';
                tag.dataset.value = val;
                tag.innerHTML = `${text} <span class="tag-close">×</span>`;
                tag.querySelector('.tag-close').addEventListener('click', (ev) => {
                    ev.stopPropagation();
                    tag.remove();
                    opt.classList.remove('selected');
                    updateSelectAllState();
                    if (tagsDisplay.querySelectorAll('.tag').length === 0) {
                        const ph = tagsDisplay.querySelector('.placeholder');
                        if (ph) ph.style.display = 'block';
                    }
                });
                tagsDisplay.appendChild(tag);
                const ph = tagsDisplay.querySelector('.placeholder');
                if (ph) ph.style.display = 'none';
            } else if (!targetState && currentlySelected) {
                opt.classList.remove('selected');
                const tag = tagsDisplay.querySelector(`.tag[data-value="${val}"]`);
                if (tag) tag.remove();
                if (tagsDisplay.querySelectorAll('.tag').length === 0) {
                    const ph = tagsDisplay.querySelector('.placeholder');
                    if (ph) ph.style.display = 'block';
                }
            }
        };

        if (selectAllOpt) {
            selectAllOpt.addEventListener('click', (e) => {
                e.stopPropagation();
                const isSelected = selectAllOpt.classList.contains('selected');
                const checkbox = selectAllOpt.querySelector('input[type="checkbox"]');
                const targetState = !isSelected;

                options.forEach(opt => toggleOption(opt, targetState));
                selectAllOpt.classList.toggle('selected', targetState);
                if (checkbox) checkbox.checked = targetState;

                // Close dropdown after selecting all
                dropdown.classList.remove('show');
            });
        }

        options.forEach(opt => {
            opt.addEventListener('click', (e) => {
                e.stopPropagation();
                toggleOption(opt);
                updateSelectAllState();
            });
        });
    };

    setupMultiSelect('browser-multiselect', 'Select Browsers...');
    setupMultiSelect('resolution-multiselect', 'Select Resolutions...');
    setupMultiSelect('options-multiselect', 'Select Options...');

    // --- History Management ---




    // --- Device Lab Logic ---
    const deviceLabContainer = document.querySelector('.device-frames-container');
    if (deviceLabContainer) {
        const urlInput = document.querySelector('.url-input-wrapper input');
        const loadBtn = document.querySelector('.load-btn');
        const orientationBtns = document.querySelectorAll('.orientation-btn');
        const addSizeBtn = document.querySelector('.add-size-btn');
        const addAllToggle = document.querySelector('.device-lab-controls .toggle-switch input');
        const widthInput = document.getElementById('custom-width');
        const heightInput = document.getElementById('custom-height');
        const syncScrollToggle = document.getElementById('sync-scroll-toggle');
        let isSyncing = false;

        // Store iframe data for sync scroll
        const iframeData = new Map();

        const handleScroll = (e) => {
            if (!syncScrollToggle || !syncScrollToggle.checked || isSyncing) return;

            const sourceWin = e.target.defaultView || e.target;
            const targetIframe = sourceWin.frameElement;
            if (!targetIframe) return;

            // Get iframe IDs for tracking
            const sourceIframeId = targetIframe.dataset.iframeId || Math.random().toString(36).substr(2, 9);
            if (!targetIframe.dataset.iframeId) {
                targetIframe.dataset.iframeId = sourceIframeId;
            }

            // Try to get scroll positions, with fallbacks for cross-origin restrictions
            let scrollX = 0, scrollY = 0, scrollHeight = 0, scrollWidth = 0;

            try {
                scrollX = sourceWin.scrollX || sourceWin.pageXOffset;
                scrollY = sourceWin.scrollY || sourceWin.pageYOffset;

                const doc = sourceWin.document.documentElement;
                scrollHeight = doc.scrollHeight - sourceWin.innerHeight;
                scrollWidth = doc.scrollWidth - sourceWin.innerWidth;
            } catch (err) {
                // If direct access fails due to cross-origin restrictions, try alternative approach
                scrollX = sourceWin.scrollX || sourceWin.pageXOffset || 0;
                scrollY = sourceWin.scrollY || sourceWin.pageYOffset || 0;

                // Estimate dimensions from the iframe element itself if document access is blocked
                try {
                    const rect = targetIframe.getBoundingClientRect();
                    scrollHeight = targetIframe.contentDocument?.documentElement?.scrollHeight - targetIframe.clientHeight || 0;
                    scrollWidth = targetIframe.contentDocument?.documentElement?.scrollWidth - targetIframe.clientWidth || 0;
                } catch (e) {
                    // If all access is blocked, use a default calculation
                    scrollHeight = Math.max(sourceWin.document.body.scrollHeight, sourceWin.document.documentElement.scrollHeight) - sourceWin.innerHeight;
                    scrollWidth = Math.max(sourceWin.document.body.scrollWidth, sourceWin.document.documentElement.scrollWidth) - sourceWin.innerWidth;
                }
            }

            // Only proceed if there's actual scroll range
            if (scrollHeight <= 0 && scrollWidth <= 0) return;

            const pctY = scrollHeight > 0 ? scrollY / scrollHeight : 0;
            const pctX = scrollWidth > 0 ? scrollX / scrollWidth : 0;

            // Store the scroll percentage for this iframe
            iframeData.set(sourceIframeId, { pctX, pctY, scrollWidth, scrollHeight });

            // Mark as syncing to prevent feedback loops
            isSyncing = true;

            // Send scroll data to other iframes using postMessage
            document.querySelectorAll('.device-content').forEach(iframe => {
                if (iframe !== targetIframe && iframe.contentWindow) {
                    const targetIframeId = iframe.dataset.iframeId || Math.random().toString(36).substr(2, 9);
                    if (!iframe.dataset.iframeId) {
                        iframe.dataset.iframeId = targetIframeId;
                    }

                    // Send scroll command to other iframes
                    iframe.contentWindow.postMessage({
                        type: 'syncScroll',
                        sourceIframeId: sourceIframeId,
                        targetIframeId: targetIframeId,
                        pctX: pctX,
                        pctY: pctY,
                        scrollWidth: scrollWidth,
                        scrollHeight: scrollHeight
                    }, '*'); // In a production environment, you should specify the origin
                }
            });

            // Use requestAnimationFrame to ensure smooth animation and proper timing
            requestAnimationFrame(() => {
                isSyncing = false;
            });
        };

        // Handle messages from iframes for sync scrolling
        window.addEventListener('message', function (event) {
            // Check if this is a sync scroll message from an iframe
            if (event.data && event.data.type === 'syncScroll' && syncScrollToggle && syncScrollToggle.checked && !isSyncing) {
                isSyncing = true;

                // Find the target iframe by ID
                const targetIframe = document.querySelector(`.device-content[data-iframe-id="${event.data.targetIframeId}"]`);

                if (targetIframe && targetIframe.contentWindow) {
                    try {
                        // Send a message back to the iframe to scroll to the specified position
                        targetIframe.contentWindow.postMessage({
                            type: 'scrollTo',
                            pctX: event.data.pctX,
                            pctY: event.data.pctY,
                            scrollWidth: event.data.scrollWidth,
                            scrollHeight: event.data.scrollHeight
                        }, '*');
                    } catch (err) {
                        console.debug('Error sending scroll command to iframe:', err.message);
                    }
                }

                // Release the sync lock after a brief moment
                setTimeout(() => {
                    isSyncing = false;
                }, 50);
            }
            // Handle scroll events sent from iframes
            else if (event.data && event.data.type === 'iframeScroll' && syncScrollToggle && syncScrollToggle.checked && !isSyncing) {
                isSyncing = true;

                // Find the source iframe to exclude it from sync
                const sourceIframe = event.source.frameElement;
                if (!sourceIframe || !sourceIframe.dataset.iframeId) return;

                const sourceIframeId = sourceIframe.dataset.iframeId;

                // Calculate percentages based on the source iframe's scroll
                const pctX = event.data.scrollWidth > 0 ? event.data.scrollX / event.data.scrollWidth : 0;
                const pctY = event.data.scrollHeight > 0 ? event.data.scrollY / event.data.scrollHeight : 0;

                // Send scroll command to all other iframes
                document.querySelectorAll('.device-content').forEach(iframe => {
                    if (iframe !== sourceIframe && iframe.contentWindow) {
                        const targetIframeId = iframe.dataset.iframeId || Math.random().toString(36).substr(2, 9);
                        if (!iframe.dataset.iframeId) {
                            iframe.dataset.iframeId = targetIframeId;
                        }

                        // Send scroll command to other iframes
                        iframe.contentWindow.postMessage({
                            type: 'scrollTo',
                            pctX: pctX,
                            pctY: pctY,
                            scrollWidth: event.data.scrollWidth,
                            scrollHeight: event.data.scrollHeight
                        }, '*');
                    }
                });

                // Release the sync lock after a brief moment
                setTimeout(() => {
                    isSyncing = false;
                }, 50);
            }
        });

        const enableSyncScroll = (iframe) => {
            const attachScrollListener = () => {
                try {
                    // Check if we have access to the iframe's content window
                    if (iframe.contentWindow && iframe.contentDocument) {
                        // Remove existing to avoid duplicates if any
                        iframe.contentWindow.removeEventListener('scroll', handleScroll);
                        iframe.contentWindow.addEventListener('scroll', handleScroll);
                        console.log('Sync scroll attached to iframe');
                    }
                } catch (err) {
                    console.warn('Cannot access iframe for scroll sync (likely cross-origin):', err.message);
                    // For cross-origin iframes, we'll try to attach the listener differently
                    // Set a small timeout to retry attachment after content loads
                    setTimeout(attachScrollListener, 500);
                }
            };

            // Try to attach immediately in case content is already loaded
            if (iframe.contentDocument && iframe.contentDocument.readyState === 'complete') {
                attachScrollListener();
            }

            // Also attach to the load event for when iframe content loads
            iframe.addEventListener('load', () => {
                console.log('Iframe loaded, attempting to attach sync scroll');
                // Small delay to ensure content is fully loaded
                setTimeout(attachScrollListener, 100);

                // Add a script to the iframe to handle scroll synchronization
                setTimeout(() => {
                    try {
                        if (iframe.contentWindow) {
                            // Inject a script into the iframe to handle scrolling
                            const script = iframe.contentWindow.document.createElement('script');
                            script.textContent = `
                                // Store last scroll position to prevent loops
                                let lastScrollX = -1;
                                let lastScrollY = -1;
                                        
                                // Listen for scroll commands from parent
                                window.addEventListener('message', function(event) {
                                    if (event.data && event.data.type === 'scrollTo') {
                                        // Calculate target scroll position
                                        const targetX = event.data.pctX * event.data.scrollWidth;
                                        const targetY = event.data.pctY * event.data.scrollHeight;
                                                
                                        // Prevent scroll loops
                                        if (Math.abs(targetX - lastScrollX) > 5 || Math.abs(targetY - lastScrollY) > 5) {
                                            // Update last scroll position
                                            lastScrollX = targetX;
                                            lastScrollY = targetY;
                                                    
                                            // Scroll to position
                                            window.scrollTo(targetX, targetY);
                                        }
                                    }
                                });
                                        
                                // Send scroll events to parent
                                window.addEventListener('scroll', function() {
                                    // Throttle scroll events
                                    if (this.scrollTimer) {
                                        clearTimeout(this.scrollTimer);
                                    }
                                            
                                    this.scrollTimer = setTimeout(() => {
                                        // Only send if this scroll wasn't triggered by sync
                                        if (Math.abs(window.scrollX - lastScrollX) <= 5 && Math.abs(window.scrollY - lastScrollY) <= 5) {
                                            // This is a synced scroll, don't send back
                                            return;
                                        }
                                                
                                        // Update last scroll position
                                        lastScrollX = window.scrollX;
                                        lastScrollY = window.scrollY;
                                                
                                        // Send scroll data to parent
                                        parent.postMessage({
                                            type: 'iframeScroll',
                                            scrollX: window.scrollX,
                                            scrollY: window.scrollY,
                                            scrollHeight: document.documentElement.scrollHeight - window.innerHeight,
                                            scrollWidth: document.documentElement.scrollWidth - window.innerWidth
                                        }, '*');
                                    }, 100);
                                });
                            `;

                            // Append the script to the iframe's document
                            if (iframe.contentDocument && iframe.contentDocument.head) {
                                iframe.contentDocument.head.appendChild(script);
                            }
                        }
                    } catch (err) {
                        console.warn('Could not inject sync scroll script into iframe:', err.message);
                    }
                }, 200); // Wait a bit more to ensure the iframe content is loaded
            });
        };

        // Track the last URL that credits were deducted for
        let lastCreditedUrl = null;

        // Helper to deduct a credit for a new URL
        const deductCreditForUrl = async (url) => {
            if (url === lastCreditedUrl) return true; // Same URL, no charge
            try {
                const response = await fetch('/api/live/search', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: url })
                });
                if (!response.ok) {
                    const data = await response.json();
                    if (response.status === 403 || (data.error && data.error.toLowerCase().includes('credits'))) {
                        window.showAlert('Credits Exhausted', 'Your credits are finished. Please top up to continue.');
                    } else if (typeof showToast === 'function') {
                        showToast(data.error || 'Insufficient credits', 'error');
                    } else {
                        alert(data.error || 'Insufficient credits');
                    }
                    return false;
                }
                const data = await response.json();

                // Low Credit Popup logic for Device Lab
                if (data.low_credits) {
                    window.showAlert('Low Credits Warning', 'Your credit balance is low (50 or below). Please top up soon to avoid interruption.');
                }

                lastCreditedUrl = url;
                // Update credit display in header
                const creditSpan = document.querySelector('.credits-display-header span:last-child');
                if (creditSpan) {
                    const currentCredits = parseInt(creditSpan.textContent);
                    if (!isNaN(currentCredits)) {
                        creditSpan.textContent = currentCredits - 1;
                    }
                }
                return true;
            } catch (err) {
                console.error('Credit deduction error:', err);
                return false;
            }
        };

        const updateDeviceUrls = async (url) => {
            if (!url) return;
            if (!url.startsWith('http')) url = 'https://' + url;

            // Only deduct credit if URL changed
            const ok = await deductCreditForUrl(url);
            if (!ok) return;

            // Notify user of wait time for staging URLs
            const isStaging = ['staging', 'stagging', 'preview', 'ourwebsitepreview'].some(keyword => url.toLowerCase().includes(keyword));
            if (isStaging && typeof showToast === 'function') {
                showToast("Staging URL detected - verifying security challenge. Please wait 15-20 seconds for the devices to load.", "info");
            }

            const proxiedUrl = `/api/proxy?url=${encodeURIComponent(url)}`;
            console.log('Loading proxied URL:', proxiedUrl);
            document.querySelectorAll('.device-frame').forEach(frame => {
                const iframe = frame.querySelector('.device-content');
                const placeholder = frame.querySelector('.device-placeholder');
                if (iframe) {
                    iframe.src = proxiedUrl;
                    iframe.style.display = 'block';
                }
                if (placeholder) {
                    placeholder.style.display = 'none';
                }
            });
        };

        // Initialize existing frames
        document.querySelectorAll('.device-content').forEach(enableSyncScroll);

        if (loadBtn && urlInput) {
            loadBtn.addEventListener('click', () => updateDeviceUrls(urlInput.value));
            urlInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') updateDeviceUrls(urlInput.value);
            });
        }

        orientationBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                orientationBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const isLandscape = btn.title === 'Landscape';

                // Add landscape-mode class to container for CSS rules to pick up (important for mobile)
                if (isLandscape) {
                    deviceLabContainer.classList.add('landscape-mode');
                } else {
                    deviceLabContainer.classList.remove('landscape-mode');
                }

                document.querySelectorAll('.device-frame-wrapper').forEach(wrapper => {
                    const frame = wrapper.querySelector('.device-frame');
                    const span = wrapper.querySelector('.device-header span');

                    // Get current dimensions from the span text
                    const match = span.textContent.match(/(\d+)\s*x\s*(\d+)/);
                    if (match) {
                        let w = parseInt(match[1]);
                        let h = parseInt(match[2]);

                        if (isLandscape && w < h) {
                            [w, h] = [h, w];
                        } else if (!isLandscape && w > h) {
                            [w, h] = [h, w];
                        }

                        // Apply inline styles (mostly for desktop, CSS handles mobile)
                        frame.style.width = `${w}px`;
                        frame.style.height = `${h}px`;
                        span.textContent = span.textContent.replace(/\d+\s*x\s*\d+/, `${w} x ${h}`);
                    }
                });
            });
        });

        if (addSizeBtn) {
            addSizeBtn.addEventListener('click', async () => {
                const w = widthInput.value || 375;
                const h = heightInput.value || 667;
                let url = urlInput.value || 'about:blank';
                if (url !== 'about:blank') {
                    if (!url.startsWith('http')) url = 'https://' + url;
                    // Deduct credit if URL changed
                    const ok = await deductCreditForUrl(url);
                    if (!ok) return;
                    url = `/api/proxy?url=${encodeURIComponent(url)}`;
                }

                const wrapper = document.createElement('div');
                wrapper.className = 'device-frame-wrapper';
                wrapper.innerHTML = `
                    <div class="device-header">
                        <img src="/static/svg/phone-icon.svg" width="18" height="18">
                        <span>Custom (${w} x ${h})</span>
                        <img src="/static/svg/close-red.svg" class="device-close" width="16" height="16">
                    </div>
                    <div class="device-frame" style="width: ${w}px; height: ${h}px;">
                        <div class="device-placeholder" style="${url !== 'about:blank' ? 'display: none;' : ''}">
                            <img src="/static/svg/web-icon.svg">
                            <h3>Ready to Test</h3>
                            <p>Enter a URL above to start testing on this device.</p>
                        </div>
                        <iframe src="${url}" class="device-content" style="${url !== 'about:blank' ? 'display: block;' : ''}"></iframe>
                    </div>
                `;
                deviceLabContainer.prepend(wrapper);
                const newIframe = wrapper.querySelector('.device-content');
                enableSyncScroll(newIframe);
            });
        }

        if (addAllToggle) {
            addAllToggle.addEventListener('change', async () => {
                if (addAllToggle.checked) {
                    let url = urlInput.value || 'about:blank';
                    if (url !== 'about:blank') {
                        if (!url.startsWith('http')) url = 'https://' + url;
                        // Deduct credit once for all presets (only if URL changed)
                        const ok = await deductCreditForUrl(url);
                        if (!ok) {
                            addAllToggle.checked = false;
                            return;
                        }
                        url = `/api/proxy?url=${encodeURIComponent(url)}`;
                    }

                    const presets = [
                        { name: 'iPhone SE', w: 375, h: 667, icon: 'phone-icon' },
                        { name: 'iPhone 14 Pro', w: 393, h: 852, icon: 'phone-icon' },
                        { name: 'Pixel 7', w: 412, h: 915, icon: 'phone-icon' },
                        { name: 'iPad Air', w: 820, h: 1180, icon: 'tablet-icon' },
                        { name: 'MacBook Air', w: 1280, h: 800, icon: 'tablet-icon' }
                    ];

                    // Reverse snapshots to maintain their relative order when prepending
                    presets.reverse().forEach(p => {
                        const wrapper = document.createElement('div');
                        wrapper.className = 'device-frame-wrapper';
                        wrapper.dataset.isPreset = "true";
                        wrapper.innerHTML = `
                            <div class="device-header">
                                <img src="/static/svg/${p.icon}.svg" width="18" height="18">
                                <span>${p.name} (${p.w} x ${p.h})</span>
                                <img src="/static/svg/close-red.svg" class="device-close" width="16" height="16">
                            </div>
                            <div class="device-frame" style="width: ${p.w}px; height: ${p.h}px;">
                                <div class="device-placeholder" style="${url !== 'about:blank' ? 'display: none;' : ''}">
                                    <img src="/static/svg/web-icon.svg">
                                    <h3>Ready to Test</h3>
                                    <p>Enter a URL above to start testing on this device.</p>
                                </div>
                                <iframe src="${url}" class="device-content" style="${url !== 'about:blank' ? 'display: block;' : ''}"></iframe>
                            </div>
                        `;
                        deviceLabContainer.prepend(wrapper);
                        const newIframe = wrapper.querySelector('.device-content');
                        enableSyncScroll(newIframe);
                    });
                } else {
                    // Remove all frames tagged as presets
                    document.querySelectorAll('.device-frame-wrapper[data-is-preset="true"]').forEach(wrapper => {
                        wrapper.remove();
                    });
                }
            });
        }

        deviceLabContainer.addEventListener('click', (e) => {
            if (e.target.classList.contains('device-close')) {
                e.target.closest('.device-frame-wrapper').remove();
            }
        });
    }

    // --- Global Session Management (for History & Dashboard) ---
    window.deleteSession = async (sessionId) => {
        if (!await window.showConfirm('Permanently Delete?', 'Are you sure you want to permanently delete this session? This action cannot be undone.')) return;

        try {
            const response = await fetch(`/api/audit/${sessionId}`, { method: 'DELETE' });
            if (response.ok) {
                window.location.reload();
            } else {
                showToast('Failed to delete session.', 'error');
            }
        } catch (error) {
            console.error('Delete error:', error);
            showToast('An error occurred while deleting.', 'error');
        }
    };

    window.restartSession = async (sessionId, type = null) => {
        if (!await window.showConfirm('Restart Session?', 'Are you sure you want to restart this audit session?')) return;

        try {
            const response = await fetch(`/api/audit/${sessionId}/restart`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            if (response.ok) {
                const data = await response.json();
                const newSessionId = data.session_id;
                currentSessionId = newSessionId; // Update global state

                // CRITICAL: Clear any existing polling interval first
                if (pollInterval) {
                    clearInterval(pollInterval);
                    pollInterval = null;
                }

                const auditModal = document.getElementById('audit-modal') || document.getElementById('progress-modal');
                if (auditModal) {
                    // Reset modal UI BEFORE showing it
                    if (typeof resetModalUI === 'function') resetModalUI();

                    // Now show the modal
                    auditModal.style.display = 'flex';

                    if (typeof startPolling === 'function') {
                        // If type not provided, try to infer it robustly
                        if (!type) {
                            const params = new URLSearchParams(window.location.search);
                            type = params.get('type');
                        }

                        // Fallback inference if still null
                        if (!type) {
                            const path = window.location.pathname;
                            if (path.includes('static')) type = 'static';
                            else if (path.includes('dynamic')) type = 'dynamic';
                            else if (path.includes('performance')) type = 'performance';
                            else if (path.includes('accessibility')) type = 'accessibility';
                            else if (path.includes('meta-tags')) type = 'meta-tags';
                            else if (path.includes('image-alt')) type = 'image-alt';
                            else if (path.includes('sitemaps')) type = 'sitemap';
                            else if (path.includes('h1')) type = 'h1';
                            else if (path.includes('phone')) type = 'phone';
                            else type = 'static';
                        }

                        console.log(`[RESTART] Starting polling for type: ${type}, new session: ${newSessionId}`);
                        startPolling(type, newSessionId);
                    } else {
                        window.location.reload();
                    }
                } else {
                    window.location.reload();
                }
            } else {
                const errorData = await response.json();
                if (response.status === 403 || (errorData.error && errorData.error.toLowerCase().includes('credits'))) {
                    window.showAlert('Credits Exhausted', 'Your credits are finished. Please top up to continue.');
                } else {
                    showToast(errorData.error || 'Failed to restart session.', 'error');
                }
            }
        } catch (error) {
            console.error('Restart error:', error);
            showToast('An error occurred while restarting.', 'error');
        }
    };
});
