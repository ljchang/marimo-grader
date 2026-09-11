import { mount } from 'svelte';
import './app.css';
import App from './App.svelte';
import { router } from '$lib/router.svelte';
import { auth } from '$lib/auth.svelte';

router.start();
void auth.load();

const app = mount(App, {
  target: document.getElementById('app')!,
});

export default app;
