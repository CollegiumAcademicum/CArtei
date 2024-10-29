# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.db import models


class Group(models.Model):
    id = models.IntegerField(primary_key=True)

    class Meta:
        managed = False
        db_table = 'Group'


class AuthGroup(models.Model):
    name = models.CharField(unique=True, max_length=150)

    class Meta:
        managed = False
        db_table = 'auth_group'


class AuthGroupPermissions(models.Model):
    id = models.BigAutoField(primary_key=True)
    group = models.ForeignKey(AuthGroup, models.DO_NOTHING)
    permission = models.ForeignKey('AuthPermission', models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'auth_group_permissions'
        unique_together = (('group', 'permission'),)


class AuthPermission(models.Model):
    name = models.CharField(max_length=255)
    content_type = models.ForeignKey('DjangoContentType', models.DO_NOTHING)
    codename = models.CharField(max_length=100)

    class Meta:
        managed = False
        db_table = 'auth_permission'
        unique_together = (('content_type', 'codename'),)


class AuthUser(models.Model):
    password = models.CharField(max_length=128)
    last_login = models.DateTimeField(blank=True, null=True)
    is_superuser = models.BooleanField()
    username = models.CharField(unique=True, max_length=150)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    email = models.CharField(max_length=254)
    is_staff = models.BooleanField()
    is_active = models.BooleanField()
    date_joined = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'auth_user'


class AuthUserGroups(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(AuthUser, models.DO_NOTHING)
    group = models.ForeignKey(AuthGroup, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'auth_user_groups'
        unique_together = (('user', 'group'),)


class AuthUserUserPermissions(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(AuthUser, models.DO_NOTHING)
    permission = models.ForeignKey(AuthPermission, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'auth_user_user_permissions'
        unique_together = (('user', 'permission'),)


class Contract(models.Model):
    id = models.OneToOneField('Rentingparty', models.DO_NOTHING, db_column='id', primary_key=True)
    liv = models.ForeignKey('Livingunit', models.DO_NOTHING)
    path_to_file = models.TextField(blank=True, null=True)
    date_of_start = models.DateField(blank=True, null=True)
    date_of_end = models.DateField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'contract'
        unique_together = (('id', 'liv'), ('id', 'liv'),)


class Dataprivstatement(models.Model):
    date_of_signing = models.DateField(blank=True, null=True)
    id = models.IntegerField(primary_key=True)
    ren = models.ForeignKey('Person', models.DO_NOTHING)
    per_id = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'dataprivstatement'


class DjangoAdminLog(models.Model):
    action_time = models.DateTimeField()
    object_id = models.TextField(blank=True, null=True)
    object_repr = models.CharField(max_length=200)
    action_flag = models.SmallIntegerField()
    change_message = models.TextField()
    content_type = models.ForeignKey('DjangoContentType', models.DO_NOTHING, blank=True, null=True)
    user = models.ForeignKey(AuthUser, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'django_admin_log'


class DjangoContentType(models.Model):
    app_label = models.CharField(max_length=100)
    model = models.CharField(max_length=100)

    class Meta:
        managed = False
        db_table = 'django_content_type'
        unique_together = (('app_label', 'model'),)


class DjangoMigrations(models.Model):
    id = models.BigAutoField(primary_key=True)
    app = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    applied = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'django_migrations'


class DjangoSession(models.Model):
    session_key = models.CharField(primary_key=True, max_length=40)
    session_data = models.TextField()
    expire_date = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'django_session'


class FreeipaAuthTile(models.Model):
    id = models.BigAutoField(primary_key=True)
    title = models.CharField(max_length=100)
    link = models.CharField(max_length=200)

    class Meta:
        managed = False
        db_table = 'freeipa_auth_tile'


class FreeipaAuthUsertilesetting(models.Model):
    id = models.BigAutoField(primary_key=True)
    position = models.IntegerField()
    tile = models.ForeignKey(FreeipaAuthTile, models.DO_NOTHING)
    user = models.ForeignKey(AuthUser, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'freeipa_auth_usertilesetting'
        unique_together = (('user', 'tile'),)


class GroupHasLivingUnits(models.Model):
    gro = models.OneToOneField('Livingunit', models.DO_NOTHING, primary_key=True)
    id = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'group_has_living_units'
        unique_together = (('gro', 'id'), ('gro', 'id'),)


class Handoverprotocol(models.Model):
    id = models.OneToOneField('Rentingparty', models.DO_NOTHING, db_column='id', primary_key=True)
    liv = models.ForeignKey('Livingunit', models.DO_NOTHING)
    received_key = models.BooleanField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'handoverprotocol'
        unique_together = (('id', 'liv'), ('id', 'liv'),)


class IncidentalCostPerAreaComp(models.Model):
    ren = models.OneToOneField('Incidlcost', models.DO_NOTHING, primary_key=True)
    liv_id = models.IntegerField()
    inc = models.ForeignKey('Perareacost', models.DO_NOTHING)
    id = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'incidental_cost_per_area_comp'
        unique_together = (('ren', 'liv_id', 'inc', 'id'), ('ren', 'liv_id', 'inc', 'id'),)


class IncidentalCostPerPersonComp(models.Model):
    ren = models.OneToOneField('Incidlcost', models.DO_NOTHING, primary_key=True)
    liv_id = models.IntegerField()
    inc = models.ForeignKey('Perperscost', models.DO_NOTHING)
    id = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'incidental_cost_per_person_comp'
        unique_together = (('ren', 'liv_id', 'inc', 'id'), ('ren', 'liv_id', 'inc', 'id'),)


class IncidentalCostUsageComponent(models.Model):
    ren = models.OneToOneField('Incidlcost', models.DO_NOTHING, primary_key=True)
    liv_id = models.IntegerField()
    inc = models.ForeignKey('Usagecost', models.DO_NOTHING)
    id = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'incidental_cost_usage_component'
        unique_together = (('ren', 'liv_id', 'inc', 'id'), ('ren', 'liv_id', 'inc', 'id'),)


class Incidlcost(models.Model):
    ren = models.OneToOneField('Rentingparty', models.DO_NOTHING, primary_key=True)
    liv = models.ForeignKey('Livingunit', models.DO_NOTHING)
    id = models.IntegerField()
    amount = models.DecimalField(max_digits=2, decimal_places=0, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'incidlcost'
        unique_together = (('ren', 'liv', 'id'), ('ren', 'liv', 'id'),)


class Livingunit(models.Model):
    id = models.OneToOneField('Residentialcategory', models.DO_NOTHING, db_column='id', primary_key=True)
    res_id = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'livingunit'


class Maintenant(models.Model):
    ren = models.OneToOneField('Person', models.DO_NOTHING, primary_key=True)
    id = models.IntegerField()
    sub_ren = models.ForeignKey('Subtenant', models.DO_NOTHING, blank=True, null=True)
    sub_id = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'maintenant'
        unique_together = (('ren', 'id'), ('ren', 'id'),)


class Perareacost(models.Model):
    id = models.IntegerField(primary_key=True)

    class Meta:
        managed = False
        db_table = 'perareacost'


class Perperscost(models.Model):
    id = models.IntegerField(primary_key=True)

    class Meta:
        managed = False
        db_table = 'perperscost'


class Person(models.Model):
    ren = models.OneToOneField('Rentingparty', models.DO_NOTHING, primary_key=True)
    id = models.IntegerField()
    first_names = models.TextField(blank=True, null=True)
    last_names = models.TextField(blank=True, null=True)
    preferred_name = models.TextField(blank=True, null=True)
    pronouns = models.TextField(blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    phone_number = models.IntegerField(blank=True, null=True)
    email = models.TextField(blank=True, null=True)
    study_subject = models.TextField(blank=True, null=True)
    educational_institution = models.TextField(blank=True, null=True)
    dat = models.ForeignKey(Dataprivstatement, models.DO_NOTHING, blank=True, null=True)
    pho = models.ForeignKey('Photoallowance', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'person'
        unique_together = (('ren', 'id'), ('ren', 'id'),)


class Photoallowance(models.Model):
    date_of_signing = models.DateField(blank=True, null=True)
    id = models.IntegerField(primary_key=True)
    ren = models.ForeignKey(Person, models.DO_NOTHING)
    per_id = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'photoallowance'


class Rentingparty(models.Model):
    id = models.IntegerField(primary_key=True)

    class Meta:
        managed = False
        db_table = 'rentingparty'


class Residentialcategory(models.Model):
    id = models.IntegerField(primary_key=True)

    class Meta:
        managed = False
        db_table = 'residentialcategory'


class Secundarytenant(models.Model):
    per_ren = models.OneToOneField(Person, models.DO_NOTHING, primary_key=True)
    id = models.IntegerField()
    ren = models.ForeignKey('Subtenant', models.DO_NOTHING, blank=True, null=True)
    sub_id = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'secundarytenant'
        unique_together = (('per_ren', 'id'), ('per_ren', 'id'),)


class Subtenant(models.Model):
    ren = models.OneToOneField(Person, models.DO_NOTHING, primary_key=True)
    id = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'subtenant'
        unique_together = (('ren', 'id'), ('ren', 'id'),)


class Usagecost(models.Model):
    id = models.IntegerField(primary_key=True)

    class Meta:
        managed = False
        db_table = 'usagecost'

