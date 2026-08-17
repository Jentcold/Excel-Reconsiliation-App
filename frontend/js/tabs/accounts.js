import { api } from '../api.js';
import { clear, el, emptyState, notice, spinner, toast } from '../ui.js';

const ROLES = [
  ['commercial', 'Commercial — sees everything'],
  ['sales', 'Sales — items & prices only'],
  ['admin', 'Admin — manages accounts'],
];

export default async function renderAccounts(view, user) {
  clear(view).append(spinner('Loading accounts…'));

  let users;
  try {
    ({ users } = await api.users());
  } catch (error) {
    clear(view).append(notice(error.message, 'err'));
    return;
  }

  clear(view);
  view.append(createForm(view, user));
  view.append(users.length ? accountTable(users, view, user) : emptyState('No accounts yet.'));
}

function createForm(view, user) {
  const panel = el('div', { class: 'panel' }, [el('h2', { text: 'Create an account' })]);

  const name = el('input', { type: 'text', placeholder: 'Full name' });
  const email = el('input', { type: 'email', placeholder: 'name@company.com' });
  const password = el('input', { type: 'password', placeholder: 'At least 8 characters', autocomplete: 'new-password' });
  const role = el('select');
  for (const [value, label] of ROLES) role.append(el('option', { value, text: label }));

  const row = el('div', { class: 'row', style: 'align-items:flex-end' }, [
    el('div', { style: 'flex:1;min-width:150px' }, [el('label', { text: 'Name' }), name]),
    el('div', { style: 'flex:1;min-width:180px' }, [el('label', { text: 'Email' }), email]),
    el('div', { style: 'flex:1;min-width:160px' }, [el('label', { text: 'Temporary password' }), password]),
    el('div', { style: 'flex:1;min-width:180px' }, [el('label', { text: 'Role' }), role]),
    el('button', {
      class: 'primary',
      text: 'Create',
      onclick: async (event) => {
        if (password.value.length < 8) {
          toast('Password must be at least 8 characters.', 'warn');
          return;
        }
        event.target.disabled = true;
        try {
          const result = await api.createUser({
            name: name.value.trim(),
            email: email.value.trim(),
            password: password.value,
            role: role.value,
          });
          toast(result.message, 'ok');
          renderAccounts(view, user);
        } catch (error) {
          toast(error.message, 'err');
          event.target.disabled = false;
        }
      },
    }),
  ]);

  panel.append(row);
  panel.append(el('p', {
    class: 'muted',
    style: 'margin:12px 0 0',
    text: 'Share the temporary password with the account holder directly, and ask them to have it changed.',
  }));
  return panel;
}

function accountTable(users, view, admin) {
  const table = el('table', { class: 'data' });
  table.append(el('thead', {}, el('tr', {}, [
    el('th', { text: 'Name' }),
    el('th', { text: 'Email' }),
    el('th', { text: 'Role' }),
    el('th', { text: 'Created' }),
    el('th', { text: '' }),
  ])));

  const body = el('tbody');
  for (const account of users) {
    const isSelf = account.id === admin.id;

    const roleSelect = el('select', { style: 'width:150px' });
    for (const [value, label] of ROLES) {
      roleSelect.append(el('option', { value, text: label.split(' — ')[0] }));
    }
    roleSelect.value = account.role;
    roleSelect.disabled = isSelf;
    roleSelect.addEventListener('change', async () => {
      try {
        const result = await api.setUserRole(account.id, roleSelect.value);
        toast(result.message, 'ok');
      } catch (error) {
        toast(error.message, 'err');
        roleSelect.value = account.role;
      }
    });

    const actions = el('div', { class: 'row' }, [
      el('button', {
        text: 'Reset password',
        onclick: async () => {
          const next = prompt(`New password for ${account.email} (at least 8 characters):`);
          if (next === null) return;
          if (next.length < 8) { toast('Password must be at least 8 characters.', 'warn'); return; }
          try {
            const result = await api.setUserPassword(account.id, next);
            toast(result.message, 'ok');
          } catch (error) {
            toast(error.message, 'err');
          }
        },
      }),
      !isSelf && el('button', {
        class: 'danger',
        text: 'Delete',
        onclick: async () => {
          if (!confirm(`Delete the account for ${account.email}? This can't be undone.`)) return;
          try {
            const result = await api.deleteUser(account.id);
            toast(result.message, 'ok');
            renderAccounts(view, admin);
          } catch (error) {
            toast(error.message, 'err');
          }
        },
      }),
    ].filter(Boolean));

    body.append(el('tr', {}, [
      el('td', { text: account.name || '—' }),
      el('td', { text: account.email }),
      el('td', {}, roleSelect),
      el('td', { text: account.created_at ? new Date(account.created_at).toLocaleDateString() : '—' }),
      el('td', {}, actions),
    ]));
  }
  table.append(body);
  return el('div', { class: 'table-scroll' }, table);
}
