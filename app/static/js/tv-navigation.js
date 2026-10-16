/**
 * FilmsOverWeb - LG webOS & Smart TV Spatial Navigation Engine
 * Provides full D-pad remote control (Up/Down/Left/Right/OK/Back)
 * with Netflix/Prime Video style rail scrolling and focus rings.
 */

(function () {
    'use strict';

    let currentFocus = null;
    let isTvMode = false;
    let isNavigating = false;

    // Standard TV Remote KeyCodes
    const KEYS = {
        LEFT: [37, 'ArrowLeft'],
        UP: [38, 'ArrowUp'],
        RIGHT: [39, 'ArrowRight'],
        DOWN: [40, 'ArrowDown'],
        ENTER: [13, 'Enter', 'Select'],
        BACK: [461, 10009, 27, 'Back', 'Escape'], // 461=webOS, 10009=Tizen
        PLAY: [415, 'MediaPlay'],
        PAUSE: [19, 'MediaPause'],
        PLAY_PAUSE: [10252, 'MediaPlayPause']
    };

    function isKey(e, keyDef) {
        return keyDef.includes(e.keyCode) || keyDef.includes(e.key);
    }

    function isElementVisible(el) {
        if (!el || !el.getBoundingClientRect) return false;
        if (el.getAttribute('tabindex') === '-1') return false;
        if (el.disabled) return false;

        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
            return false;
        }

        // Check if inside a hidden hero slide
        const hiddenSlide = el.closest('.hero-slide.opacity-0');
        if (hiddenSlide) return false;

        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    function setFocus(el, scrollToView = true) {
        if (!el || el === currentFocus) return;

        if (currentFocus) {
            currentFocus.classList.remove('tv-focused');
        }

        currentFocus = el;
        isTvMode = true;
        currentFocus.classList.add('tv-focused');

        try {
            currentFocus.focus({ preventScroll: true });
        } catch (_) {}

        // Handle horizontal scrolling inside .carousel-track
        const track = el.closest('.carousel-track');
        if (track) {
            const trackRect = track.getBoundingClientRect();
            const elRect = el.getBoundingClientRect();
            const currentScroll = track.scrollLeft;
            const tileCenterRelativeToTrack = (elRect.left - trackRect.left) + (elRect.width / 2);
            const targetScroll = currentScroll + tileCenterRelativeToTrack - (trackRect.width / 2);
            track.scrollTo({ left: Math.max(0, targetScroll), behavior: 'smooth' });
        }

        // Handle vertical scrolling for the whole page
        if (scrollToView) {
            const rect = el.getBoundingClientRect();
            const topMargin = 100; // Account for fixed navbar
            const bottomMargin = 80;

            if (rect.top < topMargin || rect.bottom > window.innerHeight - bottomMargin) {
                el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        }
    }

    function getFocusableCandidates() {
        const selector = 'a[href], button:not([disabled]), input:not([type="hidden"]), select, textarea, [tabindex="0"]';
        const all = Array.from(document.querySelectorAll(selector));
        return all.filter(isElementVisible);
    }

    function findClosestHorizontally(elements, targetX) {
        if (!elements || elements.length === 0) return null;
        let closest = null;
        let minDiff = Infinity;

        elements.forEach(el => {
            const rect = el.getBoundingClientRect();
            const centerX = rect.left + rect.width / 2;
            const diff = Math.abs(centerX - targetX);
            if (diff < minDiff) {
                minDiff = diff;
                closest = el;
            }
        });

        return closest;
    }

    function handleCarouselNavigation(direction) {
        if (!currentFocus) return false;
        const track = currentFocus.closest('.carousel-track');
        if (!track) return false;

        if (direction === 'RIGHT') {
            const next = currentFocus.nextElementSibling;
            if (next && isElementVisible(next)) {
                setFocus(next);
                return true;
            }
            return true; // Already at end of track
        }

        if (direction === 'LEFT') {
            const prev = currentFocus.previousElementSibling;
            if (prev && isElementVisible(prev)) {
                setFocus(prev);
                return true;
            }
            return true; // Already at start of track
        }

        const allTracks = Array.from(document.querySelectorAll('.carousel-track')).filter(isElementVisible);
        const currentTrackIndex = allTracks.indexOf(track);
        const currentRect = currentFocus.getBoundingClientRect();
        const currentCenterX = currentRect.left + currentRect.width / 2;

        if (direction === 'DOWN') {
            if (currentTrackIndex >= 0 && currentTrackIndex < allTracks.length - 1) {
                const nextTrack = allTracks[currentTrackIndex + 1];
                const tiles = Array.from(nextTrack.children).filter(isElementVisible);
                const target = findClosestHorizontally(tiles, currentCenterX) || tiles[0];
                if (target) {
                    setFocus(target);
                    return true;
                }
            }
            return false; // Let spatial search find footer or bottom links
        }

        if (direction === 'UP') {
            if (currentTrackIndex > 0) {
                const prevTrack = allTracks[currentTrackIndex - 1];
                const tiles = Array.from(prevTrack.children).filter(isElementVisible);
                const target = findClosestHorizontally(tiles, currentCenterX) || tiles[0];
                if (target) {
                    setFocus(target);
                    return true;
                }
            } else {
                // At top-most rail: move up to Hero Billboard action buttons or Navbar
                const activeHeroSlide = document.querySelector('.hero-slide.opacity-100') || document.querySelector('.hero-slide:not(.opacity-0)');
                if (activeHeroSlide) {
                    const heroWatchBtn = activeHeroSlide.querySelector('.hero-watch-btn');
                    if (heroWatchBtn && isElementVisible(heroWatchBtn)) {
                        setFocus(heroWatchBtn);
                        return true;
                    }
                }

                // If no hero, move to navbar
                const navLinks = Array.from(document.querySelectorAll('nav a, nav button, nav input')).filter(isElementVisible);
                const targetNav = findClosestHorizontally(navLinks, currentCenterX) || navLinks[0];
                if (targetNav) {
                    setFocus(targetNav);
                    return true;
                }
            }
        }

        return false;
    }

    function handleHeroNavigation(direction) {
        if (!currentFocus) return false;
        const heroSlide = currentFocus.closest('.hero-slide');
        if (!heroSlide) return false;

        const isWatchBtn = currentFocus.classList.contains('hero-watch-btn');
        const isDetailsBtn = currentFocus.classList.contains('hero-details-btn');

        if (isWatchBtn && direction === 'RIGHT') {
            const detailsBtn = heroSlide.querySelector('.hero-details-btn');
            if (detailsBtn && isElementVisible(detailsBtn)) {
                setFocus(detailsBtn);
                return true;
            }
        }

        if (isDetailsBtn && direction === 'LEFT') {
            const watchBtn = heroSlide.querySelector('.hero-watch-btn');
            if (watchBtn && isElementVisible(watchBtn)) {
                setFocus(watchBtn);
                return true;
            }
        }

        if (direction === 'DOWN') {
            // Drop down into first carousel track
            const firstTrack = document.querySelector('.carousel-track');
            if (firstTrack) {
                const firstTile = firstTrack.querySelector('.movie-tile, .series-tile') || firstTrack.firstElementChild;
                if (firstTile && isElementVisible(firstTile)) {
                    setFocus(firstTile);
                    return true;
                }
            }
        }

        if (direction === 'UP') {
            // Jump to navbar
            const navLink = document.querySelector('nav a[href="/movies"]') || document.querySelector('nav a');
            if (navLink && isElementVisible(navLink)) {
                setFocus(navLink);
                return true;
            }
        }

        return false;
    }

    function handleNavbarNavigation(direction) {
        if (!currentFocus) return false;
        const nav = currentFocus.closest('nav');
        if (!nav) return false;

        const navItems = Array.from(nav.querySelectorAll('a, button, input:not([type="hidden"])')).filter(isElementVisible);
        const idx = navItems.indexOf(currentFocus);

        if (direction === 'RIGHT' && idx >= 0 && idx < navItems.length - 1) {
            setFocus(navItems[idx + 1]);
            return true;
        }

        if (direction === 'LEFT' && idx > 0) {
            setFocus(navItems[idx - 1]);
            return true;
        }

        if (direction === 'DOWN') {
            // Check for Hero buttons
            const activeHero = document.querySelector('.hero-slide.opacity-100') || document.querySelector('.hero-slide:not(.opacity-0)');
            if (activeHero) {
                const watchBtn = activeHero.querySelector('.hero-watch-btn');
                if (watchBtn && isElementVisible(watchBtn)) {
                    setFocus(watchBtn);
                    return true;
                }
            }

            // Or first carousel rail
            const firstTile = document.querySelector('.carousel-track .movie-tile, .carousel-track .series-tile');
            if (firstTile && isElementVisible(firstTile)) {
                setFocus(firstTile);
                return true;
            }

            // Or first card on listing pages
            const firstCard = document.querySelector('.grid a');
            if (firstCard && isElementVisible(firstCard)) {
                setFocus(firstCard);
                return true;
            }
        }

        return false;
    }

    function handleSpatialSearch(direction) {
        if (!currentFocus) return false;

        const currRect = currentFocus.getBoundingClientRect();
        const currCenterX = currRect.left + currRect.width / 2;
        const currCenterY = currRect.top + currRect.height / 2;

        const candidates = getFocusableCandidates().filter(c => c !== currentFocus);
        let bestCandidate = null;
        let bestScore = Infinity;

        candidates.forEach(cand => {
            const r = cand.getBoundingClientRect();
            const candCenterX = r.left + r.width / 2;
            const candCenterY = r.top + r.height / 2;

            let primaryDiff = 0;
            let orthoDiff = 0;
            let isValidDirection = false;

            switch (direction) {
                case 'RIGHT':
                    if (r.left >= currRect.right - 8) {
                        primaryDiff = r.left - currRect.right;
                        orthoDiff = Math.abs(candCenterY - currCenterY);
                        isValidDirection = true;
                    }
                    break;
                case 'LEFT':
                    if (r.right <= currRect.left + 8) {
                        primaryDiff = currRect.left - r.right;
                        orthoDiff = Math.abs(candCenterY - currCenterY);
                        isValidDirection = true;
                    }
                    break;
                case 'DOWN':
                    if (r.top >= currRect.bottom - 8) {
                        primaryDiff = r.top - currRect.bottom;
                        orthoDiff = Math.abs(candCenterX - currCenterX);
                        isValidDirection = true;
                    }
                    break;
                case 'UP':
                    if (r.bottom <= currRect.top + 8) {
                        primaryDiff = currRect.top - r.bottom;
                        orthoDiff = Math.abs(candCenterX - currCenterX);
                        isValidDirection = true;
                    }
                    break;
            }

            if (isValidDirection) {
                const score = primaryDiff + (orthoDiff * 2.5);
                if (score < bestScore) {
                    bestScore = score;
                    bestCandidate = cand;
                }
            }
        });

        if (bestCandidate) {
            setFocus(bestCandidate);
            return true;
        }

        return false;
    }

    function moveFocus(direction) {
        if (!currentFocus) {
            initDefaultFocus();
            return;
        }

        // Try specialized carousel navigation first
        if (handleCarouselNavigation(direction)) return;

        // Try Hero buttons navigation
        if (handleHeroNavigation(direction)) return;

        // Try Navbar navigation
        if (handleNavbarNavigation(direction)) return;

        // Fallback to geometric spatial search (for grids, details, settings)
        handleSpatialSearch(direction);
    }

    function initDefaultFocus() {
        // Priority 1: Hero Billboard "Watch Now" button
        const activeHero = document.querySelector('.hero-slide.opacity-100') || document.querySelector('.hero-slide:not(.opacity-0)');
        if (activeHero) {
            const watchBtn = activeHero.querySelector('.hero-watch-btn');
            if (watchBtn && isElementVisible(watchBtn)) {
                setFocus(watchBtn, false);
                return;
            }
        }

        // Priority 2: First tile in the first carousel track
        const firstTile = document.querySelector('.carousel-track .movie-tile, .carousel-track .series-tile');
        if (firstTile && isElementVisible(firstTile)) {
            setFocus(firstTile, false);
            return;
        }

        // Priority 3: First card in any grid
        const firstGridCard = document.querySelector('.grid a, .movie-tile');
        if (firstGridCard && isElementVisible(firstGridCard)) {
            setFocus(firstGridCard, false);
            return;
        }

        // Priority 4: Play button on watch page
        const playBtn = document.querySelector('button[title*="Play"], .cinema-backdrop a');
        if (playBtn && isElementVisible(playBtn)) {
            setFocus(playBtn, false);
            return;
        }

        // Priority 5: Navbar Movies link
        const navMovies = document.querySelector('nav a[href="/movies"]');
        if (navMovies && isElementVisible(navMovies)) {
            setFocus(navMovies, false);
            return;
        }
    }

    // Main Keyboard & Remote Control Handler
    window.addEventListener('keydown', function (e) {
        if (isNavigating) return;

        // D-Pad Directional Navigation
        if (isKey(e, KEYS.UP)) {
            e.preventDefault();
            moveFocus('UP');
            return;
        }

        if (isKey(e, KEYS.DOWN)) {
            e.preventDefault();
            moveFocus('DOWN');
            return;
        }

        if (isKey(e, KEYS.LEFT)) {
            e.preventDefault();
            moveFocus('LEFT');
            return;
        }

        if (isKey(e, KEYS.RIGHT)) {
            e.preventDefault();
            moveFocus('RIGHT');
            return;
        }

        // Enter / OK button
        if (isKey(e, KEYS.ENTER)) {
            if (currentFocus) {
                // If it's an input and not yet focused, let default focus handle it
                if (currentFocus.tagName === 'INPUT' || currentFocus.tagName === 'TEXTAREA') {
                    currentFocus.focus();
                    return;
                }

                e.preventDefault();
                currentFocus.classList.add('tv-pressed');
                setTimeout(() => {
                    if (currentFocus) currentFocus.classList.remove('tv-pressed');
                }, 140);

                isNavigating = true;
                setTimeout(() => { isNavigating = false; }, 800);

                // Trigger click
                currentFocus.click();
            }
            return;
        }

        // Back button (LG webOS: 461)
        if (isKey(e, KEYS.BACK)) {
            // Close any open dropdowns or modals first
            const userDropdown = document.getElementById('user-menu-dropdown');
            if (userDropdown && !userDropdown.classList.contains('hidden')) {
                e.preventDefault();
                userDropdown.classList.add('hidden');
                return;
            }

            const qualityDropdown = document.getElementById('quality-dropdown');
            if (qualityDropdown && !qualityDropdown.classList.contains('hidden')) {
                e.preventDefault();
                qualityDropdown.classList.add('hidden');
                return;
            }

            const engineDropdown = document.getElementById('engine-dropdown');
            if (engineDropdown && !engineDropdown.classList.contains('hidden')) {
                e.preventDefault();
                engineDropdown.classList.add('hidden');
                return;
            }

            const epDropdown = document.getElementById('ep-dropdown');
            if (epDropdown && !epDropdown.classList.contains('hidden')) {
                e.preventDefault();
                epDropdown.classList.add('hidden');
                return;
            }

            // If not on homepage or login, navigate back in browser history
            if (window.location.pathname !== '/' && window.location.pathname !== '/login') {
                e.preventDefault();
                window.history.back();
            }
            return;
        }

        // Play / Pause Media Keys
        if (isKey(e, KEYS.PLAY) || isKey(e, KEYS.PAUSE) || isKey(e, KEYS.PLAY_PAUSE)) {
            const video = document.querySelector('video') || document.querySelector('movi-player');
            if (video) {
                e.preventDefault();
                if (typeof video.togglePlay === 'function') {
                    video.togglePlay();
                } else if (video.paused) {
                    video.play();
                } else {
                    video.pause();
                }
            }
        }
    });

    // Remove TV focus ring if user moves mouse significantly (Desktop experience)
    let mouseMoveCount = 0;
    window.addEventListener('mousemove', function () {
        mouseMoveCount++;
        if (mouseMoveCount > 3 && isTvMode) {
            isTvMode = false;
            if (currentFocus) {
                currentFocus.classList.remove('tv-focused');
            }
        }
    });

    // Auto-focus on boot
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initDefaultFocus);
    } else {
        setTimeout(initDefaultFocus, 100);
    }

    // Expose TV Navigation API globally
    window.TvNav = {
        setFocus: setFocus,
        getFocus: () => currentFocus,
        moveFocus: moveFocus,
        refresh: initDefaultFocus
    };

})();
