(function () {
  const config = window.HELPERA_SUPABASE || {};
  const hasConfig = Boolean(config.url && config.anonKey && window.supabase);
  const client = hasConfig ? window.supabase.createClient(config.url, config.anonKey) : null;

  const localKeys = {
    volunteerProfiles: 'volunteerProfiles',
    activeVolunteerProfileId: 'activeVolunteerProfileId',
    ngoProfiles: 'ngoProfiles',
    activeNgoProfileId: 'activeNgoProfileId',
    applications: 'helperaApplications'
  };

  const getLocal = (key) => JSON.parse(localStorage.getItem(key) || '[]');
  const setLocal = (key, value) => localStorage.setItem(key, JSON.stringify(value));

  const getId = (prefix) => {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
    return `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
  };

  const normalizeVolunteer = (row) => row && ({
    profileId: row.id || row.profileId,
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

  async function updateVolunteerProfile(profileId, patch) {
    if (!profileId) return null;
    if (client) {
      const payload = {};
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

  async function updateNgoProfile(profileId, patch) {
    if (!profileId) return null;
    if (client) {
      const payload = {};
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
        .select('*, tasks(id, title, format, ngo_profile_id, ngo_profiles(org_name, about, contacts)), volunteer_profiles(id, contact, account, about, skills, interests)')
        .eq('id', applicationId)
        .single();
      if (error) return null;
      return data;
    }
    return getLocal(localKeys.applications).find((item) => item.id === applicationId) || null;
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

  async function listApplications(filters = {}) {
    if (client) {
      let query = client
        .from('applications')
        .select('*, tasks(id, title, format, ngo_profile_id, ngo_profiles(org_name, about, contacts)), volunteer_profiles(id, contact, account, about, skills, interests)')
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
    updateVolunteerProfile,
    createNgoProfile,
    getNgoProfile,
    updateNgoProfile,
    createTask,
    listTasks,
    getTask,
    createApplication,
    getApplication,
    updateApplication,
    listApplications
  };
})();
