
===================
``squarelet.users``
===================

.. currentmodule:: squarelet.users

``User`` Model
==============

The user model is how we store information about each user account in the database.  We only store information generally useful about users here.  Application specific configurations are only stored in each client application.

Fields
------

.. class:: models.User

    .. attribute:: id

        :class:`~django.db.models.UUIDField`

        We use a UUID for the primary key in order to be able to uniquely identify a user across sites

    .. attribute:: name

        :class:`~django.db.models.CharField`

        This is the full name of the user.  It is used to sign public records requests and for communications with the user.  If a user is uncomfortable sharing their real name, they are encouraged to supply us with a pseudonym, with the understanding this may prevent them from taking legal action on rejected requests.  For a more in depth reason as to why we prefer a single full name field to a first and last name column, please see `Falsehoods Programmers Believe About Names <https://www.kalzumeus.com/2010/06/17/falsehoods-programmers-believe-about-names/>`_.

        - Required
        - Not unique
        - Public
        - Unicode allowed
        - Max length of 255 characters

    .. attribute:: email

        :class:`~django.db.models.EmailField`

        This is the user's primary email.  It is used to communicate with the user as well as the user being allowed to login with it.

        - Required
        - Unique
        - Private, but leakable - if someone tries to register with an email address that is in use, an error will be shown that the email address is already registered
        - Unicode allowed
        - Max length of 254 characters (as per the email spec)
        - Case insensitive, but preserves initial case
        - TODO How multiple email addresses and verification works

    .. attribute:: username

        :class:`~django.db.models.CharField`

        This is the user's username for logging in and for specifying on their profile page.

        - Required
        - Unique
        - Public
        - May not contain unicode.  May only contain letters, numbers, ``.``, ``-``, and ``_``.
        - Max length of 150 characters
        - Case insensitive, but preserves initial case
        - The user may edit this value once

    .. attribute:: password

        :class:`~django.db.models.CharField`

        Hash of the users password.  We will use the `argon2 <https://password-hashing.net/#argon2>`_ hash to store passwords.  We will also accept ``pbkdf2_sha256`` and ``bcrypt`` as this is what MuckRock and DocumentCloud used, respectively.  These will be upgraded to ``argon2`` upon user login.  We will have a minimum password length of 8, a similarity check to the username, name and email fields, a common password check and a numeric only password check.

        - Required

    .. attribute:: avatar

        :class:`~django.db.models.ImageField`

        A profile image associates with the user

    .. attribute:: is_active

        :class:`~django.db.models.BooleanField`

        It is recommended to set this field to ``False`` instead of deleting user models, in order to protect the database integrity.  This may require scurbbing some fields in order to not mantain data we no longer need.

    .. attribute:: is_superuser

        :class:`~django.db.models.BooleanField`

        This is used for the Django admin site.  It specifies that the user is to have all permissions without explicitly granting them.

    .. attribute:: is_staff

        :class:`~django.db.models.BooleanField`

        This is used for the Django admin site.  It specifies that the user may access the admin site.

    .. attribute:: groups

        :class:`~django.db.models.ManyToManyField` to
        :class:`~django.contrib.auth.models.Group`

        This is used for the Django admin site.  It assigns the user to a group, which has certain permissions mapped to it.

    .. attribute:: user_permissions

        :class:`~django.db.models.ManyToManyField` to
        :class:`~django.contrib.auth.models.Permission`

        This is used for the Django admin site.  It explicilty maps certain permissions to the user.

    .. attribute:: last_login

        :class:`~django.db.models.DateTimeField`

        This is the date and time of the last login for the user.

    .. attribute:: created_at

        :class:`~django.db.models.DateTimeField`

        This is the date and time this user account was created.

    .. attribute:: updated_at

        :class:`~django.db.models.DateTimeField`

        This is the date and time this user account was last updated.
