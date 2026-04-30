(function () {
  const config = window.HELPERA_SUPABASE || {};
  const hasConfig = Boolean(config.url && config.anonKey && window.supabase);
  const client = hasConfig ? window.supabase.createClient(config.url, config.anonKey) : null;

  const localKeys = {
    volunteerProfiles: 'volunteerProfiles',
    activeVolunteerProfileId: 'activeVolunteerProfileId',
    ngoProfiles: 'ngoProfiles',
    activeNgoProfileId: 'activeNgoProfileId',
    applications: 'helperaApplications',
    appEvents: 'helperaAppEvents'
  };

  const getLocal = (key) => JSON.parse(localStorage.getItem(key) || '[]');
  const setLocal = (key, value) => localStorage.setItem(key, JSON.stringify(value));

  const getId = (prefix) => {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
    return `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
  };

  const normalizeVolunteer = (row) => row && ({
    profileId: row.id || row.profileId,
    userId: row.user_id || row.userId,
    createdAt: row.created_at || row.createdAt,
    registrationStep: row.registration_step || row.registrationStep,
    account: row.account || { contact: row.contact },
    about: row.about || {},
    skills: row.skills || {},
    interests: row.interests || {},
    notifications: row.notifications || {}
  });

  const normalizeNgo = (row) => row && ({
    profileId: row.id || row.profileId,
    userId: row.user_id || row.userId,
    createdAt: row.created_at || row.createdAt,
    registrationStep: row.registration_step || row.registrationStep,
    account: row.account || {},
    about: row.about || {},
    contacts: row.contacts || {},
    firstTask: row.first_task || row.firstTask || {}
  });

  const upsertLocal = (storageKey, profileId, patch) => {
    const profiles = getLocal(storageKey);
    const index = profiles.findIndex((item) => item.profileId === profileId);
    if (index === -1) {
      profiles.push({ profileId, createdAt: new Date().toISOString(), ...patch });
    } else {
      profiles[index] = { ...profiles[index], ...patch };
    }
    setLocal(storageKey, profiles);
    return profiles.find((item) => item.profileId === profileId);
  };

  async function createVolunteerProfile(account) {
    if (client) {
      const { data, error } = await client
        .from('volunteer_profiles')
        .insert({
          user_id: account.userId || null,
          contact: account.contact,
          account,
          registration_step: 'account'
        })
        .select()
        .single();
      if (error) throw error;
      localStorage.setItem(localKeys.activeVolunteerProfileId, data.id);
      return normalizeVolunteer(data);
    }

    const profileId = getId('volunteer');
    const profile = {
      profileId,
      userId: account.userId || null,
      createdAt: new Date().toISOString(),
      registrationStep: 'account',
      account,
      about: {},
      skills: {},
      interests: {},
      notifications: {}
    };
    const profiles = getLocal(localKeys.volunteerProfiles);
    profiles.push(profile);
    setLocal(localKeys.volunteerProfiles, profiles);
    localStorage.setItem(localKeys.activeVolunteerProfileId, profileId);
    return profile;
  }

  async function getVolunteerProfile(profileId) {
    if (!profileId) return null;
    if (client) {
      const { data, error } = await client.from('volunteer_profiles').select('*').eq('id', profileId).single();
      if (error) return null;
      return normalizeVolunteer(data);
    }
    return getLocal(localKeys.volunteerProfiles).find((item) => item.profileId === profileId) || null;
  }

  async function getVolunteerProfileByUser(userId, contact) {
    if (!userId && !contact) return null;
    if (client) {
      const byUser = userId
        ? await client.from('volunteer_profiles').select('*').eq('user_id', userId).limit(1)
        : { data: [], error: null };
      if (byUser.error) return null;
      if (byUser.data?.length) return normalizeVolunteer(byUser.data[0]);

      if (contact) {
        const byContact = await client.from('volunteer_profiles').select('*').eq('contact', contact).limit(1);
        if (byContact.error || !byContact.data?.length) return null;
        const profile = normalizeVolunteer(byContact.data[0]);
        if (userId && !profile.userId) await updateVolunteerProfile(profile.profileId, { userId });
        return { ...profile, userId: profile.userId || userId };
      }
      return null;
    }
    return getLocal(localKeys.volunteerProfiles).find((item) => item.userId === userId || item.account?.contact === contact) || null;
  }

  async function updateVolunteerProfile(profileId, patch) {
    if (!profileId) return null;
    if (client) {
      const payload = {};
      if ('userId' in patch) payload.user_id = patch.userId;
      if ('registrationStep' in patch) payload.registration_step = patch.registrationStep;
      if ('account' in patch) payload.account = patch.account;
      if ('about' in patch) payload.about = patch.about;
      if ('skills' in patch) payload.skills = patch.skills;
      if ('interests' in patch) payload.interests = patch.interests;
      if ('notifications' in patch) payload.notifications = patch.notifications;

      const { data, error } = await client
        .from('volunteer_profiles')
        .update(payload)
        .eq('id', profileId)
        .select()
        .single();
      if (error) throw error;
      localStorage.setItem(localKeys.activeVolunteerProfileId, profileId);
      return normalizeVolunteer(data);
    }
    localStorage.setItem(localKeys.activeVolunteerProfileId, profileId);
    return upsertLocal(localKeys.volunteerProfiles, profileId, patch);
  }

  async function createNgoProfile(account) {
    if (client) {
      const { data, error } = await client
        .from('ngo_profiles')
        .insert({
          user_id: account.userId || null,
          org_name: account.orgName,
          contact: account.contact,
          account,
          registration_step: 'account'
        })
        .select()
        .single();
      if (error) throw error;
      localStorage.setItem(localKeys.activeNgoProfileId, data.id);
      return normalizeNgo(data);
    }

    const profileId = getId('ngo');
    const profile = {
      profileId,
      userId: account.userId || null,
      createdAt: new Date().toISOString(),
      registrationStep: 'account',
      account,
      about: {},
      contacts: {},
      firstTask: {}
    };
    const profiles = getLocal(localKeys.ngoProfiles);
    profiles.push(profile);
    setLocal(localKeys.ngoProfiles, profiles);
    localStorage.setItem(localKeys.activeNgoProfileId, profileId);
    return profile;
  }

  async function getNgoProfile(profileId) {
    if (!profileId) return null;
    if (client) {
      const { data, error } = await client.from('ngo_profiles').select('*').eq('id', profileId).single();
      if (error) return null;
      return normalizeNgo(data);
    }
    return getLocal(localKeys.ngoProfiles).find((item) => item.profileId === profileId) || null;
  }

  async function getNgoProfileByUser(userId, contact) {
    if (!userId && !contact) return null;
    if (client) {
      const byUser = userId
        ? await client.from('ngo_profiles').select('*').eq('user_id', userId).limit(1)
        : { data: [], error: null };
      if (byUser.error) return null;
      if (byUser.data?.length) return normalizeNgo(byUser.data[0]);

      if (contact) {
        const byContact = await client.from('ngo_profiles').select('*').eq('contact', contact).limit(1);
        if (byContact.error || !byContact.data?.length) return null;
        const profile = normalizeNgo(byContact.data[0]);
        if (userId && !profile.userId) await updateNgoProfile(profile.profileId, { userId });
        return { ...profile, userId: profile.userId || userId };
      }
      return null;
    }
    return getLocal(localKeys.ngoProfiles).find((item) => item.userId === userId || item.account?.contact === contact) || null;
  }

  async function updateNgoProfile(profileId, patch) {
    if (!profileId) return null;
    if (client) {
      const payload = {};
      if ('userId' in patch) payload.user_id = patch.userId;
      if ('registrationStep' in patch) payload.registration_step = patch.registrationStep;
      if ('account' in patch) payload.account = patch.account;
      if ('about' in patch) payload.about = patch.about;
      if ('contacts' in patch) payload.contacts = patch.contacts;
      if ('firstTask' in patch) payload.first_task = patch.firstTask;

      const { data, error } = await client
        .from('ngo_profiles')
        .update(payload)
        .eq('id', profileId)
        .select()
        .single();
      if (error) throw error;
      localStorage.setItem(localKeys.activeNgoProfileId, profileId);
      return normalizeNgo(data);
    }
    localStorage.setItem(localKeys.activeNgoProfileId, profileId);
    return upsertLocal(localKeys.ngoProfiles, profileId, patch);
  }

  async function createTask(ngoProfileId, task) {
    if (client) {
      const { data, error } = await client
        .from('tasks')
        .insert({
          ngo_profile_id: ngoProfileId,
          title: task.title,
          description: task.description,
          format: task.format,
          skills: task.skills,
          date_start: task.dateStart || null,
          date_end: task.dateEnd || null,
          payload: task,
          status: 'published'
        })
        .select()
        .single();
      if (error) throw error;
      return data;
    }

    const profile = await getNgoProfile(ngoProfileId);
    await updateNgoProfile(ngoProfileId, { firstTask: task, registrationStep: 'completed' });
    return {
      id: getId('task'),
      ngo_profile_id: ngoProfileId,
      title: task.title,
      description: task.description,
      format: task.format,
      skills: task.skills,
      payload: task,
      ngo_profile: profile
    };
  }

  async function listTasks() {
    if (client) {
      const { data, error } = await client
        .from('tasks')
        .select('*, ngo_profiles(org_name, about, contacts)')
        .eq('status', 'published')
        .order('created_at', { ascending: false });
      if (error) throw error;
      return data || [];
    }

    return getLocal(localKeys.ngoProfiles)
      .filter((profile) => profile.firstTask && profile.firstTask.title)
      .map((profile) => ({
        id: profile.profileId,
        ngo_profile_id: profile.profileId,
        title: profile.firstTask.title,
        description: profile.firstTask.description,
        format: profile.firstTask.format,
        skills: profile.firstTask.skills,
        payload: profile.firstTask,
        ngo_profiles: {
          org_name: profile.account?.orgName || profile.about?.shortName || 'НКО',
          about: profile.about || {},
          contacts: profile.contacts || {}
        }
      }));
  }

  async function getTask(taskId) {
    if (!taskId) return null;
    if (client) {
      const { data, error } = await client
        .from('tasks')
        .select('*, ngo_profiles(org_name, about, contacts)')
        .eq('id', taskId)
        .single();
      if (error) return null;
      return data;
    }

    return (await listTasks()).find((task) => task.id === taskId) || null;
  }

  async function createApplication(application) {
    if (client) {
      const { data, error } = await client.from('applications').insert(application).select().single();
      if (error) throw error;
      return data;
    }

    const applications = getLocal(localKeys.applications);
    const item = { id: getId('application'), created_at: new Date().toISOString(), status: 'review', ...application };
    applications.push(item);
    setLocal(localKeys.applications, applications);
    return item;
  }

  async function getApplication(applicationId) {
    if (!applicationId) return null;
    if (client) {
      const { data, error } = await client
        .from('applications')
        .select('*, tasks(id, title, format, ngo_profile_id, ngo_profiles(org_name, about, contacts)), volunteer_profiles(id, contact, account, about, skills, interests, registration_step)')
        .eq('id', applicationId)
        .single();
      if (error) return null;
      return data;
    }
    const application = getLocal(localKeys.applications).find((item) => item.id === applicationId) || null;
    if (!application) return null;
    const task = (await listTasks()).find((item) => item.id === application.task_id) || null;
    const volunteer = await getVolunteerProfile(application.volunteer_profile_id);
    return {
      ...application,
      tasks: task,
      volunteer_profiles: volunteer ? {
        id: volunteer.profileId,
        contact: volunteer.account?.contact,
        account: volunteer.account,
        about: volunteer.about,
        skills: volunteer.skills,
        interests: volunteer.interests,
        registration_step: volunteer.registrationStep
      } : null
    };
  }

  async function updateApplication(applicationId, patch) {
    if (!applicationId) return null;
    if (client) {
      const { data, error } = await client
        .from('applications')
        .update(patch)
        .eq('id', applicationId)
        .select()
        .single();
      if (error) throw error;
      return data;
    }

    const applications = getLocal(localKeys.applications);
    const index = applications.findIndex((item) => item.id === applicationId);
    if (index === -1) return null;
    applications[index] = { ...applications[index], ...patch };
    setLocal(localKeys.applications, applications);
    return applications[index];
  }

  async function logEvent(event) {
    const payload = {
      event_type: event.eventType || event.event_type,
      actor_role: event.actorRole || event.actor_role || null,
      actor_profile_id: event.actorProfileId || event.actor_profile_id || null,
      application_id: event.applicationId || event.application_id || null,
      task_id: event.taskId || event.task_id || null,
      payload: event.payload || {}
    };

    if (client) {
      const { data, error } = await client.from('app_events').insert(payload).select().single();
      if (error) {
        console.warn('Не удалось записать событие app_events. Проверьте, что supabase-schema.sql обновлён.', error);
        return null;
      }
      return data;
    }

    const events = getLocal(localKeys.appEvents);
    const item = { id: getId('event'), created_at: new Date().toISOString(), ...payload };
    events.push(item);
    setLocal(localKeys.appEvents, events);
    return item;
  }

  async function signUpWithEmail({ email, password, role, metadata = {} }) {
    if (!client) throw new Error('Supabase Auth не настроен.');
    const { data, error } = await client.auth.signUp({
      email,
      password,
      options: {
        data: {
          role,
          ...metadata
        }
      }
    });
    if (error) throw error;
    return data;
  }

  async function signInWithEmail({ email, password }) {
    if (!client) throw new Error('Supabase Auth не настроен.');
    const { data, error } = await client.auth.signInWithPassword({ email, password });
    if (error) throw error;
    return data;
  }

  async function signOut() {
    if (!client) return;
    const { error } = await client.auth.signOut();
    if (error) throw error;
  }

  async function getAuthSession() {
    if (!client) return null;
    const { data, error } = await client.auth.getSession();
    if (error) return null;
    return data.session || null;
  }

  async function getCurrentUserProfile(role) {
    const session = await getAuthSession();
    const user = session?.user;
    if (!user) return null;
    const contact = user.email || user.phone || '';
    if (role === 'ngo') return getNgoProfileByUser(user.id, contact);
    return getVolunteerProfileByUser(user.id, contact);
  }

  async function listApplications(filters = {}) {
    if (client) {
      let query = client
        .from('applications')
        .select('*, tasks(id, title, format, ngo_profile_id, ngo_profiles(org_name, about, contacts)), volunteer_profiles(id, contact, account, about, skills, interests, registration_step)')
        .order('created_at', { ascending: false });
      if (filters.volunteerProfileId) query = query.eq('volunteer_profile_id', filters.volunteerProfileId);
      if (filters.status) query = query.eq('status', filters.status);
      const { data, error } = await query;
      if (error) throw error;
      return (data || []).filter((item) => {
        if (filters.ngoProfileId && item.tasks?.ngo_profile_id !== filters.ngoProfileId) return false;
        if (filters.includeDrafts === false && item.status === 'draft') return false;
        return true;
      });
    }
    return getLocal(localKeys.applications).filter((item) => {
      if (filters.volunteerProfileId && item.volunteer_profile_id !== filters.volunteerProfileId) return false;
      if (filters.status && item.status !== filters.status) return false;
      if (filters.includeDrafts === false && item.status === 'draft') return false;
      return true;
    });
  }

  window.helperaDb = {
    isSupabaseEnabled: hasConfig,
    client,
    localKeys,
    createVolunteerProfile,
    getVolunteerProfile,
    getVolunteerProfileByUser,
    updateVolunteerProfile,
    createNgoProfile,
    getNgoProfile,
    getNgoProfileByUser,
    updateNgoProfile,
    createTask,
    listTasks,
    getTask,
    createApplication,
    getApplication,
    updateApplication,
    listApplications,
    logEvent,
    signUpWithEmail,
    signInWithEmail,
    signOut,
    getAuthSession,
    getCurrentUserProfile
  };
})();
