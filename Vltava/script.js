/* ===== Project Vltava — Enhanced Interactions ===== */

(function () {
  'use strict';

  // ========== CANVAS: Lightfall, Stars, Mouse Glow ==========
  const canvas = document.getElementById('bg-canvas');
  const ctx = canvas.getContext('2d');
  let W, H;
  let mouseX = -1000, mouseY = -1000;
  let smoothMouseX = -1000, smoothMouseY = -1000;
  let scrollY = 0;

  function resize() {
    W = canvas.width = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }
  resize();
  window.addEventListener('resize', resize);

  // --- Stars ---
  const stars = [];
  const STAR_COUNT = 180;

  function initStars() {
    stars.length = 0;
    for (let i = 0; i < STAR_COUNT; i++) {
      stars.push({
        x: Math.random() * W,
        y: Math.random() * H,
        r: Math.random() * 1.2 + 0.3,
        alpha: Math.random() * 0.6 + 0.1,
        twinkleSpeed: Math.random() * 0.015 + 0.005,
        twinkleOffset: Math.random() * Math.PI * 2
      });
    }
  }
  initStars();

  // --- Mouse particles ---
  const particles = [];
  const MAX_PARTICLES = 40;

  function spawnParticle(x, y) {
    if (particles.length >= MAX_PARTICLES) particles.shift();
    particles.push({
      x: x + (Math.random() - 0.5) * 30,
      y: y + (Math.random() - 0.5) * 30,
      vx: (Math.random() - 0.5) * 0.8,
      vy: (Math.random() - 0.5) * 0.8 - 0.3,
      r: Math.random() * 2 + 0.5,
      life: 1,
      decay: Math.random() * 0.015 + 0.01
    });
  }

  // --- Animation frame ---
  let time = 0;
  let lastSpawn = 0;

  function draw() {
    time += 0.016;
    ctx.clearRect(0, 0, W, H);

    // Smooth mouse interpolation
    smoothMouseX += (mouseX - smoothMouseX) * 0.08;
    smoothMouseY += (mouseY - smoothMouseY) * 0.08;

    // Fade factor based on scroll (effects diminish as user scrolls down)
    const heroFade = Math.max(0, 1 - scrollY / (H * 0.8));

    // --- Draw lightfall beam ---
    if (heroFade > 0.01) {
      const beamCenterX = W / 2;
      const beamPulse = Math.sin(time * 0.5) * 0.12 + 0.88;

      // Core beam (narrow, bright)
      const coreGrad = ctx.createRadialGradient(
        beamCenterX, H * 0.15, 0,
        beamCenterX, H * 0.15, H * 0.7
      );
      coreGrad.addColorStop(0, `rgba(180, 200, 255, ${0.25 * beamPulse * heroFade})`);
      coreGrad.addColorStop(0.15, `rgba(71, 139, 235, ${0.12 * beamPulse * heroFade})`);
      coreGrad.addColorStop(0.4, `rgba(100, 80, 200, ${0.04 * heroFade})`);
      coreGrad.addColorStop(1, 'transparent');
      ctx.fillStyle = coreGrad;
      ctx.fillRect(0, 0, W, H);

      // Vertical beam line (thin bright center)
      const lineGrad = ctx.createLinearGradient(0, 0, 0, H);
      lineGrad.addColorStop(0, `rgba(200, 210, 255, ${0.4 * beamPulse * heroFade})`);
      lineGrad.addColorStop(0.3, `rgba(71, 139, 235, ${0.2 * beamPulse * heroFade})`);
      lineGrad.addColorStop(0.7, `rgba(100, 80, 200, ${0.05 * heroFade})`);
      lineGrad.addColorStop(1, 'transparent');
      ctx.save();
      ctx.globalCompositeOperation = 'screen';
      ctx.fillStyle = lineGrad;
      const beamWidth = 120 + Math.sin(time * 0.3) * 20;
      ctx.fillRect(beamCenterX - beamWidth / 2, 0, beamWidth, H);

      // Extra thin bright core
      const thinGrad = ctx.createLinearGradient(0, 0, 0, H * 0.6);
      thinGrad.addColorStop(0, `rgba(255, 255, 255, ${0.15 * beamPulse * heroFade})`);
      thinGrad.addColorStop(0.5, `rgba(180, 190, 255, ${0.06 * heroFade})`);
      thinGrad.addColorStop(1, 'transparent');
      ctx.fillStyle = thinGrad;
      ctx.fillRect(beamCenterX - 3, 0, 6, H * 0.6);
      ctx.restore();

      // Horizontal lens flare
      const flareY = H * 0.35 + Math.sin(time * 0.4) * 10;
      const flareGrad = ctx.createRadialGradient(
        beamCenterX, flareY, 0,
        beamCenterX, flareY, W * 0.4
      );
      flareGrad.addColorStop(0, `rgba(71, 139, 235, ${0.06 * heroFade})`);
      flareGrad.addColorStop(0.3, `rgba(100, 80, 200, ${0.02 * heroFade})`);
      flareGrad.addColorStop(1, 'transparent');
      ctx.save();
      ctx.globalCompositeOperation = 'screen';
      ctx.scale(1, 0.15);
      ctx.fillStyle = flareGrad;
      ctx.fillRect(0, (flareY - W * 0.4) / 0.15, W, W * 0.8 / 0.15);
      ctx.restore();
    }

    // --- Draw stars ---
    if (heroFade > 0.01) {
      ctx.save();
      ctx.globalCompositeOperation = 'screen';
      for (const star of stars) {
        const twinkle = Math.sin(time * star.twinkleSpeed * 60 + star.twinkleOffset) * 0.5 + 0.5;
        const alpha = star.alpha * twinkle * heroFade;
        if (alpha < 0.02) continue;

        ctx.beginPath();
        ctx.arc(star.x, star.y, star.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(200, 210, 255, ${alpha})`;
        ctx.fill();

        // Glow for brighter stars
        if (star.r > 1) {
          ctx.beginPath();
          ctx.arc(star.x, star.y, star.r * 3, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(71, 139, 235, ${alpha * 0.15})`;
          ctx.fill();
        }
      }
      ctx.restore();
    }

    // --- Draw mouse glow ---
    if (smoothMouseX > -500) {
      const glowGrad = ctx.createRadialGradient(
        smoothMouseX, smoothMouseY, 0,
        smoothMouseX, smoothMouseY, 350
      );
      glowGrad.addColorStop(0, 'rgba(71, 139, 235, 0.06)');
      glowGrad.addColorStop(0.3, 'rgba(100, 80, 200, 0.025)');
      glowGrad.addColorStop(1, 'transparent');
      ctx.save();
      ctx.globalCompositeOperation = 'screen';
      ctx.fillStyle = glowGrad;
      ctx.fillRect(0, 0, W, H);
      ctx.restore();
    }

    // --- Draw & update particles ---
    ctx.save();
    ctx.globalCompositeOperation = 'screen';
    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i];
      p.x += p.vx;
      p.y += p.vy;
      p.life -= p.decay;
      if (p.life <= 0) {
        particles.splice(i, 1);
        continue;
      }
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r * p.life, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(71, 139, 235, ${p.life * 0.3})`;
      ctx.fill();
    }
    ctx.restore();

    requestAnimationFrame(draw);
  }
  draw();

  // ========== Mouse tracking ==========
  let moveCount = 0;
  document.addEventListener('mousemove', (e) => {
    mouseX = e.clientX;
    mouseY = e.clientY;

    // Spawn particles occasionally
    moveCount++;
    if (moveCount % 3 === 0 && scrollY < H) {
      spawnParticle(e.clientX, e.clientY);
    }
  });

  document.addEventListener('mouseleave', () => {
    mouseX = -1000;
    mouseY = -1000;
  });

  // ========== Scroll tracking ==========
  let scrollRAF = null;
  window.addEventListener('scroll', () => {
    if (scrollRAF) return;
    scrollRAF = requestAnimationFrame(() => {
      scrollY = window.scrollY;
      scrollRAF = null;
    });
  });

  // ========== Scroll-based reveal animations ==========
  const revealElements = document.querySelectorAll('.reveal');
  const revealObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
        }
      });
    },
    { threshold: 0.1, rootMargin: '0px 0px -50px 0px' }
  );
  revealElements.forEach((el) => revealObserver.observe(el));

  // ========== Counter animation for stats ==========
  const statNumbers = document.querySelectorAll('.stat .number[data-count]');
  const counterObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting && !entry.target.dataset.animated) {
          entry.target.dataset.animated = 'true';
          const target = parseInt(entry.target.dataset.count, 10);
          animateCounter(entry.target, target);
        }
      });
    },
    { threshold: 0.5 }
  );
  statNumbers.forEach((el) => counterObserver.observe(el));

  function animateCounter(el, target) {
    const duration = 1200;
    const start = performance.now();
    function tick(now) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
      el.textContent = Math.round(eased * target);
      if (progress < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  // ========== Language toggle ==========
  const langBtn = document.getElementById('lang-toggle');
  let currentLang = localStorage.getItem('vltava-lang') || 'en';

  function setLang(lang) {
    currentLang = lang;
    document.body.classList.remove('lang-en', 'lang-cs');
    document.body.classList.add('lang-' + lang);
    langBtn.textContent = lang === 'en' ? 'CZ' : 'EN';
    localStorage.setItem('vltava-lang', lang);
  }

  langBtn.addEventListener('click', () => {
    setLang(currentLang === 'en' ? 'cs' : 'en');
  });

  setLang(currentLang);

  // ========== Mobile nav toggle ==========
  const navToggle = document.getElementById('nav-toggle');
  const navLinks = document.getElementById('nav-links');

  navToggle.addEventListener('click', () => {
    navLinks.classList.toggle('open');
  });

  navLinks.querySelectorAll('a').forEach((a) => {
    a.addEventListener('click', () => {
      navLinks.classList.remove('open');
    });
  });

  // ========== Gallery Lightbox ==========
  const lightbox = document.getElementById('lightbox');
  const lightboxImg = document.getElementById('lightbox-img');
  const lightboxVideo = document.getElementById('lightbox-video');
  const lightboxCaption = document.getElementById('lightbox-caption');
  const lightboxClose = document.getElementById('lightbox-close');
  const lightboxPrev = document.getElementById('lightbox-prev');
  const lightboxNext = document.getElementById('lightbox-next');

  const galleryItems = document.querySelectorAll('.gallery-item');
  let currentIndex = 0;

  function getCaption(item) {
    const lang = currentLang;
    const cap = item.querySelector(`.caption[data-lang-${lang}]`);
    return cap ? cap.textContent : '';
  }

  function showLightboxItem(item) {
    const video = item.querySelector('video');
    const img = item.querySelector('img');
    if (video) {
      lightboxImg.style.display = 'none';
      lightboxVideo.src = video.src;
      lightboxVideo.style.display = '';
      lightboxVideo.play();
    } else {
      lightboxVideo.style.display = 'none';
      lightboxVideo.pause();
      lightboxVideo.src = '';
      lightboxImg.src = img.src;
      lightboxImg.style.display = '';
    }
    lightboxCaption.textContent = getCaption(item);
  }

  function openLightbox(index) {
    currentIndex = index;
    showLightboxItem(galleryItems[index]);
    lightbox.classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  function closeLightbox() {
    lightbox.classList.remove('active');
    document.body.style.overflow = '';
    lightboxVideo.pause();
    lightboxVideo.src = '';
  }

  function navigateLightbox(dir) {
    currentIndex = (currentIndex + dir + galleryItems.length) % galleryItems.length;
    showLightboxItem(galleryItems[currentIndex]);
  }

  galleryItems.forEach((item, i) => {
    item.addEventListener('click', () => openLightbox(i));
  });

  lightboxClose.addEventListener('click', closeLightbox);
  lightboxPrev.addEventListener('click', () => navigateLightbox(-1));
  lightboxNext.addEventListener('click', () => navigateLightbox(1));

  lightbox.addEventListener('click', (e) => {
    if (e.target === lightbox) closeLightbox();
  });

  document.addEventListener('keydown', (e) => {
    if (!lightbox.classList.contains('active')) return;
    if (e.key === 'Escape') closeLightbox();
    if (e.key === 'ArrowLeft') navigateLightbox(-1);
    if (e.key === 'ArrowRight') navigateLightbox(1);
  });

  // ========== Reinitialize stars on resize ==========
  window.addEventListener('resize', () => {
    initStars();
  });

})();
