/*==============================================================*/
/* DBMS name:      PostgreSQL 14.x                              */
/* Created on:     01/05/2024 02:14:07                          */
/*==============================================================*/


drop index CONTRACT_PK;

drop table Contract;

drop index DATA_PRIV_STAT_FK2;

drop index DATAPRIVSTATEMENT_PK;

drop table DataPrivStatement;

drop index DEPOSIT_PK;

drop table Deposit;

drop index GROUP_PK;

drop table "Group";

drop index HANDOVERPROTOCOL_PK;

drop table HandOverProtocol;

drop index INCIDENTALCOST_PK;

drop table IncidlCost;

drop index LIVINGUNIT_PK;

drop table LivingUnit;

drop index MAIN_TENANT_HAS_SUB_TENENAT_FK;

drop index MAINTENENT_PK;

drop table MainTenant;

drop index PERAREACOST_PK;

drop table PerAreaCost;

drop index PERPERSCOST_PK;

drop table PerPersCost;

drop index PERSON_PK;

drop table Person;

drop index ALLOWS_PHOTOS_DOCUMENT_FK;

drop index PHOTOALLOWANCE_PK;

drop table PhotoAllowance;

drop index RENTINGPARTY_PK;

drop table RentingParty;

drop index RESIDENTIALCATEGORY_PK;

drop table ResidentialCategory;

drop index SEC_TEN_HAS_SUB_TEN_FK;

drop index SECUNDARYTENENT_PK;

drop table SecundaryTenant;

drop index SUBTENENT_PK;

drop table SubTenant;

drop index USAGECOST_PK;

drop table UsageCost;

drop index GROUP_HAS_LIVING_UNITS_PK;

drop table group_has_living_units;

drop index INC_COST_PA_PK;

drop table incidental_cost_per_area_comp;

drop index INC_COST_PP_COMPONENT_PK;

drop table incidental_cost_per_person_comp;

drop index INC_COST_USE_PK;

drop table incidental_cost_usage_component;

/*==============================================================*/
/* Table: Contract                                              */
/*==============================================================*/
create table Contract (
   id                   integer              not null,
   Liv_id               integer              not null,
   path_to_file         text,
   date_of_start        Date,
   date_of_end          Date,
   constraint PK_CONTRACT primary key (id, Liv_id)
);

/*==============================================================*/
/* Index: CONTRACT_PK                                           */
/*==============================================================*/
create unique index CONTRACT_PK on Contract (
id,
Liv_id
);

/*==============================================================*/
/* Table: DataPrivStatement                                     */
/*==============================================================*/
create table DataPrivStatement (
   date_of_signing      Date,
   id                   integer              not null,
   Ren_id               integer              not null,
   Per_id               integer              not null,
   constraint PK_DATAPRIVSTATEMENT primary key (id)
);

/*==============================================================*/
/* Index: DATAPRIVSTATEMENT_PK                                  */
/*==============================================================*/
create unique index DATAPRIVSTATEMENT_PK on DataPrivStatement (
id
);

/*==============================================================*/
/* Index: DATA_PRIV_STAT_FK2                                    */
/*==============================================================*/
create  index DATA_PRIV_STAT_FK2 on DataPrivStatement (
Ren_id,
Per_id
);

/*==============================================================*/
/* Table: Deposit                                               */
/*==============================================================*/
create table Deposit (
   id                   integer              not null,
   Liv_id               integer              not null,
   IBAN                 string,
   constraint PK_DEPOSIT primary key (id, Liv_id)
);

/*==============================================================*/
/* Index: DEPOSIT_PK                                            */
/*==============================================================*/
create unique index DEPOSIT_PK on Deposit (
id,
Liv_id
);

/*==============================================================*/
/* Table: "Group"                                               */
/*==============================================================*/
create table "Group" (
   id                   integer              not null,
   constraint PK_GROUP primary key (id)
);

/*==============================================================*/
/* Index: GROUP_PK                                              */
/*==============================================================*/
create unique index GROUP_PK on "Group" (
id
);

/*==============================================================*/
/* Table: HandOverProtocol                                      */
/*==============================================================*/
create table HandOverProtocol (
   id                   integer              not null,
   Liv_id               integer              not null,
   received_key         boolean,
   constraint PK_HANDOVERPROTOCOL primary key (id, Liv_id)
);

/*==============================================================*/
/* Index: HANDOVERPROTOCOL_PK                                   */
/*==============================================================*/
create unique index HANDOVERPROTOCOL_PK on HandOverProtocol (
id,
Liv_id
);

/*==============================================================*/
/* Table: IncidlCost                                            */
/*==============================================================*/
create table IncidlCost (
   Ren_id               integer              not null,
   Liv_id               integer              not null,
   id                   integer              not null,
   amount               decimal(2),
   constraint PK_INCIDLCOST primary key (Ren_id, Liv_id, id)
);

/*==============================================================*/
/* Index: INCIDENTALCOST_PK                                     */
/*==============================================================*/
create unique index INCIDENTALCOST_PK on IncidlCost (
Ren_id,
Liv_id,
id
);

/*==============================================================*/
/* Table: LivingUnit                                            */
/*==============================================================*/
create table LivingUnit (
   id                   integer              not null,
   Res_id               integer              not null,
   constraint PK_LIVINGUNIT primary key (id)
);

/*==============================================================*/
/* Index: LIVINGUNIT_PK                                         */
/*==============================================================*/
create unique index LIVINGUNIT_PK on LivingUnit (
id
);

/*==============================================================*/
/* Table: MainTenant                                            */
/*==============================================================*/
create table MainTenant (
   Ren_id               integer              not null,
   id                   integer              not null,
   Sub_Ren_id           integer,
   Sub_id               integer,
   constraint PK_MAINTENANT primary key (Ren_id, id)
);

/*==============================================================*/
/* Index: MAINTENENT_PK                                         */
/*==============================================================*/
create unique index MAINTENENT_PK on MainTenant (
Ren_id,
id
);

/*==============================================================*/
/* Index: MAIN_TENANT_HAS_SUB_TENENAT_FK                        */
/*==============================================================*/
create  index MAIN_TENANT_HAS_SUB_TENENAT_FK on MainTenant (
Sub_Ren_id,
Sub_id
);

/*==============================================================*/
/* Table: PerAreaCost                                           */
/*==============================================================*/
create table PerAreaCost (
   id                   integer              not null,
   constraint PK_PERAREACOST primary key (id)
);

/*==============================================================*/
/* Index: PERAREACOST_PK                                        */
/*==============================================================*/
create unique index PERAREACOST_PK on PerAreaCost (
id
);

/*==============================================================*/
/* Table: PerPersCost                                           */
/*==============================================================*/
create table PerPersCost (
   id                   integer              not null,
   constraint PK_PERPERSCOST primary key (id)
);

/*==============================================================*/
/* Index: PERPERSCOST_PK                                        */
/*==============================================================*/
create unique index PERPERSCOST_PK on PerPersCost (
id
);

/*==============================================================*/
/* Table: Person                                                */
/*==============================================================*/
create table Person (
   Ren_id               integer              not null,
   id                   integer              not null,
   first_names          text,
   last_names           text,
   preferred_name       text,
   pronouns             text,
   date_of_birth        Date,
   phone_number         integer,
   email                text,
   study_subject        text,
   educational_institution text,
   Dat_id               integer,
   Pho_id               integer,
   constraint PK_PERSON primary key (Ren_id, id)
);

/*==============================================================*/
/* Index: PERSON_PK                                             */
/*==============================================================*/
create unique index PERSON_PK on Person (
Ren_id,
id
);

/*==============================================================*/
/* Table: PhotoAllowance                                        */
/*==============================================================*/
create table PhotoAllowance (
   date_of_signing      Date,
   id                   integer              not null,
   Ren_id               integer              not null,
   Per_id               integer              not null,
   constraint PK_PHOTOALLOWANCE primary key (id)
);

/*==============================================================*/
/* Index: PHOTOALLOWANCE_PK                                     */
/*==============================================================*/
create unique index PHOTOALLOWANCE_PK on PhotoAllowance (
id
);

/*==============================================================*/
/* Index: ALLOWS_PHOTOS_DOCUMENT_FK                             */
/*==============================================================*/
create  index ALLOWS_PHOTOS_DOCUMENT_FK on PhotoAllowance (
Ren_id,
Per_id
);

/*==============================================================*/
/* Table: RentingParty                                          */
/*==============================================================*/
create table RentingParty (
   id                   integer              not null,
   constraint PK_RENTINGPARTY primary key (id)
);

/*==============================================================*/
/* Index: RENTINGPARTY_PK                                       */
/*==============================================================*/
create unique index RENTINGPARTY_PK on RentingParty (
id
);

/*==============================================================*/
/* Table: ResidentialCategory                                   */
/*==============================================================*/
create table ResidentialCategory (
   id                   integer              not null,
   constraint PK_RESIDENTIALCATEGORY primary key (id)
);

/*==============================================================*/
/* Index: RESIDENTIALCATEGORY_PK                                */
/*==============================================================*/
create unique index RESIDENTIALCATEGORY_PK on ResidentialCategory (
id
);

/*==============================================================*/
/* Table: SecundaryTenant                                       */
/*==============================================================*/
create table SecundaryTenant (
   Per_Ren_id           integer              not null,
   id                   integer              not null,
   Ren_id               integer,
   Sub_id               integer,
   constraint PK_SECUNDARYTENANT primary key (Per_Ren_id, id)
);

/*==============================================================*/
/* Index: SECUNDARYTENANT_PK                                    */
/*==============================================================*/
create unique index SECUNDARYTENANT_PK on SecundaryTenant (
Per_Ren_id,
id
);

/*==============================================================*/
/* Index: SEC_TEN_HAS_SUB_TEN_FK                                */
/*==============================================================*/
create  index SEC_TEN_HAS_SUB_TEN_FK on SecundaryTenant (
Ren_id,
Sub_id
);

/*==============================================================*/
/* Table: SubTenant                                             */
/*==============================================================*/
create table SubTenant (
   Ren_id               integer              not null,
   id                   integer              not null,
   constraint PK_SUBTENANT primary key (Ren_id, id)
);

/*==============================================================*/
/* Index: SUBTENANT_PK                                          */
/*==============================================================*/
create unique index SUBTENANT_PK on SubTenant (
Ren_id,
id
);

/*==============================================================*/
/* Table: UsageCost                                             */
/*==============================================================*/
create table UsageCost (
   id                   integer              not null,
   constraint PK_USAGECOST primary key (id)
);

/*==============================================================*/
/* Index: USAGECOST_PK                                          */
/*==============================================================*/
create unique index USAGECOST_PK on UsageCost (
id
);

/*==============================================================*/
/* Table: group_has_living_units                                */
/*==============================================================*/
create table group_has_living_units (
   Gro_id               integer              not null,
   id                   integer              not null,
   constraint PK_GROUP_HAS_LIVING_UNITS primary key (Gro_id, id)
);

/*==============================================================*/
/* Index: GROUP_HAS_LIVING_UNITS_PK                             */
/*==============================================================*/
create unique index GROUP_HAS_LIVING_UNITS_PK on group_has_living_units (
Gro_id,
id
);

/*==============================================================*/
/* Table: incidental_cost_per_area_comp                         */
/*==============================================================*/
create table incidental_cost_per_area_comp (
   Ren_id               integer              not null,
   Liv_id               integer              not null,
   Inc_id               integer              not null,
   id                   integer              not null,
   constraint PK_INCIDENTAL_COST_PER_AREA_CO primary key (Ren_id, Liv_id, Inc_id, id)
);

/*==============================================================*/
/* Index: INC_COST_PA_PK                                        */
/*==============================================================*/
create unique index INC_COST_PA_PK on incidental_cost_per_area_comp (
Ren_id,
Liv_id,
Inc_id,
id
);

/*==============================================================*/
/* Table: incidental_cost_per_person_comp                       */
/*==============================================================*/
create table incidental_cost_per_person_comp (
   Ren_id               integer              not null,
   Liv_id               integer              not null,
   Inc_id               integer              not null,
   id                   integer              not null,
   constraint PK_INCIDENTAL_COST_PER_PERSON_ primary key (Ren_id, Liv_id, Inc_id, id)
);

/*==============================================================*/
/* Index: INC_COST_PP_COMPONENT_PK                              */
/*==============================================================*/
create unique index INC_COST_PP_COMPONENT_PK on incidental_cost_per_person_comp (
Ren_id,
Liv_id,
Inc_id,
id
);

/*==============================================================*/
/* Table: incidental_cost_usage_component                       */
/*==============================================================*/
create table incidental_cost_usage_component (
   Ren_id               integer              not null,
   Liv_id               integer              not null,
   Inc_id               integer              not null,
   id                   integer              not null,
   constraint PK_INCIDENTAL_COST_USAGE_COMPO primary key (Ren_id, Liv_id, Inc_id, id)
);

/*==============================================================*/
/* Index: INC_COST_USE_PK                                       */
/*==============================================================*/
create unique index INC_COST_USE_PK on incidental_cost_usage_component (
Ren_id,
Liv_id,
Inc_id,
id
);

alter table Contract
   add constraint FK_CONTRACT_RENT_LIVI_LIVINGUN foreign key (Liv_id)
      references LivingUnit (id)
      on delete restrict on update restrict;

alter table Contract
   add constraint FK_CONTRACT_RENT_LIVI_RENTINGP foreign key (id)
      references RentingParty (id)
      on delete restrict on update restrict;

alter table DataPrivStatement
   add constraint FK_DATAPRIV_ISSUE_DAT_PERSON foreign key (Ren_id, Per_id)
      references Person (Ren_id, id)
      on delete restrict on update restrict;

alter table Deposit
   add constraint FK_DEPOSIT_PAY_DEPOS_LIVINGUN foreign key (Liv_id)
      references LivingUnit (id)
      on delete restrict on update restrict;

alter table Deposit
   add constraint FK_DEPOSIT_PAY_DEPOS_RENTINGP foreign key (id)
      references RentingParty (id)
      on delete restrict on update restrict;

alter table HandOverProtocol
   add constraint FK_HANDOVER_HAND_OVER_LIVINGUN foreign key (Liv_id)
      references LivingUnit (id)
      on delete restrict on update restrict;

alter table HandOverProtocol
   add constraint FK_HANDOVER_HAND_OVER_RENTINGP foreign key (id)
      references RentingParty (id)
      on delete restrict on update restrict;

alter table IncidlCost
   add constraint FK_INCIDLCO_PAY_INCID_LIVINGUN foreign key (Liv_id)
      references LivingUnit (id)
      on delete restrict on update restrict;

alter table IncidlCost
   add constraint FK_INCIDLCO_PAY_INCID_RENTINGP foreign key (Ren_id)
      references RentingParty (id)
      on delete restrict on update restrict;

alter table LivingUnit
   add constraint FK_LIVINGUN_RESIDENTI_RESIDENT foreign key (id)
      references ResidentialCategory (id)
      on delete restrict on update restrict;

alter table MainTenant
   add constraint FK_MAINTENA_GENERALIZ_PERSON foreign key (Ren_id, id)
      references Person (Ren_id, id)
      on delete restrict on update restrict;

alter table MainTenant
   add constraint FK_MAINTENA_MAIN_TENA_SUBTENAN foreign key (Sub_Ren_id, Sub_id)
      references SubTenant (Ren_id, id)
      on delete restrict on update restrict;

alter table Person
   add constraint FK_PERSON_ALLOWS_PH_PHOTOALL foreign key (Pho_id)
      references PhotoAllowance (id)
      on delete restrict on update restrict;

alter table Person
   add constraint FK_PERSON_ISSUE_DAT_DATAPRIV foreign key (Dat_id)
      references DataPrivStatement (id)
      on delete restrict on update restrict;

alter table Person
   add constraint FK_PERSON_RENTING_P_RENTINGP foreign key (Ren_id)
      references RentingParty (id)
      on delete restrict on update restrict;

alter table PhotoAllowance
   add constraint FK_PHOTOALL_ALLOWS_PH_PERSON foreign key (Ren_id, Per_id)
      references Person (Ren_id, id)
      on delete restrict on update restrict;

alter table SecundaryTenant
   add constraint FK_SECUNDAR_GENERALIZ_PERSON foreign key (Per_Ren_id, id)
      references Person (Ren_id, id)
      on delete restrict on update restrict;

alter table SecundaryTenant
   add constraint FK_SECUNDAR_SECUNDARY_SUBTENAN foreign key (Ren_id, Sub_id)
      references SubTenant (Ren_id, id)
      on delete restrict on update restrict;

alter table SubTenant
   add constraint FK_SUBTENAN_GENERALIZ_PERSON foreign key (Ren_id, id)
      references Person (Ren_id, id)
      on delete restrict on update restrict;

alter table group_has_living_units
   add constraint FK_GROUP_HA_GROUP_HAS_GROUP foreign key (Gro_id)
      references "Group" (id)
      on delete restrict on update restrict;

alter table group_has_living_units
   add constraint FK_GROUP_HA_GROUP_HAS_LIVINGUN foreign key (Gro_id)
      references LivingUnit (id)
      on delete restrict on update restrict;

alter table incidental_cost_per_area_comp
   add constraint FK_INCIDENT_INCIDENTA_INCIDLCO foreign key (Ren_id, Liv_id, Inc_id)
      references IncidlCost (Ren_id, Liv_id, id)
      on delete restrict on update restrict;

alter table incidental_cost_per_area_comp
   add constraint FK_INCIDENT_INCIDENTA_PERAREAC foreign key (Inc_id)
      references PerAreaCost (id)
      on delete restrict on update restrict;

alter table incidental_cost_per_person_comp
   add constraint FK_INCIDENT_INCIDENTA_INCIDLCO foreign key (Ren_id, Liv_id, Inc_id)
      references IncidlCost (Ren_id, Liv_id, id)
      on delete restrict on update restrict;

alter table incidental_cost_per_person_comp
   add constraint FK_INCIDENT_INCIDENTA_PERPERSC foreign key (Inc_id)
      references PerPersCost (id)
      on delete restrict on update restrict;

alter table incidental_cost_usage_component
   add constraint FK_INCIDENT_INCIDENTA_INCIDLCO foreign key (Ren_id, Liv_id, Inc_id)
      references IncidlCost (Ren_id, Liv_id, id)
      on delete restrict on update restrict;

alter table incidental_cost_usage_component
   add constraint FK_INCIDENT_INCIDENTA_USAGECOS foreign key (Inc_id)
      references UsageCost (id)
      on delete restrict on update restrict;

