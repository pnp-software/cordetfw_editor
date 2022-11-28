-- phpMyAdmin SQL Dump
-- version 5.1.3
-- https://www.phpmyadmin.net/
--
-- Host: db
-- Generation Time: Nov 28, 2022 at 06:25 PM
-- Server version: 8.0.28
-- PHP Version: 8.0.16

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Database: `cordetfw`
--

-- --------------------------------------------------------

--
-- Table structure for table `admin_honeypot_loginattempt`
--

CREATE TABLE `admin_honeypot_loginattempt` (
  `id` int NOT NULL,
  `username` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `ip_address` char(39) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `session_key` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `user_agent` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
  `timestamp` datetime(6) NOT NULL,
  `path` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `auth_group`
--

CREATE TABLE `auth_group` (
  `id` int NOT NULL,
  `name` varchar(150) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `auth_group_permissions`
--

CREATE TABLE `auth_group_permissions` (
  `id` int NOT NULL,
  `group_id` int NOT NULL,
  `permission_id` int NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `auth_permission`
--

CREATE TABLE `auth_permission` (
  `id` int NOT NULL,
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `content_type_id` int NOT NULL,
  `codename` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `auth_permission`
--

INSERT INTO `auth_permission` (`id`, `name`, `content_type_id`, `codename`) VALUES
(65, 'Can add application', 17, 'add_application'),
(66, 'Can change application', 17, 'change_application'),
(67, 'Can delete application', 17, 'delete_application'),
(68, 'Can view application', 17, 'view_application'),
(69, 'Can add project', 18, 'add_project'),
(70, 'Can change project', 18, 'change_project'),
(71, 'Can delete project', 18, 'delete_project'),
(72, 'Can view project', 18, 'view_project'),
(73, 'Can add spec item', 19, 'add_specitem'),
(74, 'Can change spec item', 19, 'change_specitem'),
(75, 'Can delete spec item', 19, 'delete_specitem'),
(76, 'Can view spec item', 19, 'view_specitem'),
(77, 'Can add val set', 20, 'add_valset'),
(78, 'Can change val set', 20, 'change_valset'),
(79, 'Can delete val set', 20, 'delete_valset'),
(80, 'Can view val set', 20, 'view_valset'),
(81, 'Can add release', 21, 'add_release'),
(82, 'Can change release', 21, 'change_release'),
(83, 'Can delete release', 21, 'delete_release'),
(84, 'Can view release', 21, 'view_release'),
(85, 'Can add project user', 22, 'add_projectuser'),
(86, 'Can change project user', 22, 'change_projectuser'),
(87, 'Can delete project user', 22, 'delete_projectuser'),
(88, 'Can view project user', 22, 'view_projectuser'),
(89, 'Can add log entry', 23, 'add_logentry'),
(90, 'Can change log entry', 23, 'change_logentry'),
(91, 'Can delete log entry', 23, 'delete_logentry'),
(92, 'Can view log entry', 23, 'view_logentry'),
(93, 'Can add permission', 24, 'add_permission'),
(94, 'Can change permission', 24, 'change_permission'),
(95, 'Can delete permission', 24, 'delete_permission'),
(96, 'Can view permission', 24, 'view_permission'),
(97, 'Can add group', 25, 'add_group'),
(98, 'Can change group', 25, 'change_group'),
(99, 'Can delete group', 25, 'delete_group'),
(100, 'Can view group', 25, 'view_group'),
(101, 'Can add user', 26, 'add_user'),
(102, 'Can change user', 26, 'change_user'),
(103, 'Can delete user', 26, 'delete_user'),
(104, 'Can view user', 26, 'view_user'),
(105, 'Can add content type', 27, 'add_contenttype'),
(106, 'Can change content type', 27, 'change_contenttype'),
(107, 'Can delete content type', 27, 'delete_contenttype'),
(108, 'Can view content type', 27, 'view_contenttype'),
(109, 'Can add session', 28, 'add_session'),
(110, 'Can change session', 28, 'change_session'),
(111, 'Can delete session', 28, 'delete_session'),
(112, 'Can view session', 28, 'view_session'),
(113, 'Can add login attempt', 29, 'add_loginattempt'),
(114, 'Can change login attempt', 29, 'change_loginattempt'),
(115, 'Can delete login attempt', 29, 'delete_loginattempt'),
(116, 'Can view login attempt', 29, 'view_loginattempt'),
(117, 'Can add access attempt', 30, 'add_accessattempt'),
(118, 'Can change access attempt', 30, 'change_accessattempt'),
(119, 'Can delete access attempt', 30, 'delete_accessattempt'),
(120, 'Can view access attempt', 30, 'view_accessattempt'),
(121, 'Can add access log', 31, 'add_accesslog'),
(122, 'Can change access log', 31, 'change_accesslog'),
(123, 'Can delete access log', 31, 'delete_accesslog'),
(124, 'Can view access log', 31, 'view_accesslog'),
(125, 'Can add access failure', 32, 'add_accessfailurelog'),
(126, 'Can change access failure', 32, 'change_accessfailurelog'),
(127, 'Can delete access failure', 32, 'delete_accessfailurelog'),
(128, 'Can view access failure', 32, 'view_accessfailurelog');

-- --------------------------------------------------------

--
-- Table structure for table `auth_user`
--

CREATE TABLE `auth_user` (
  `id` int NOT NULL,
  `password` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `last_login` datetime(6) DEFAULT NULL,
  `is_superuser` tinyint(1) NOT NULL,
  `username` varchar(150) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `first_name` varchar(150) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `last_name` varchar(150) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `email` varchar(254) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_staff` tinyint(1) NOT NULL,
  `is_active` tinyint(1) NOT NULL,
  `date_joined` datetime(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `auth_user`
--

INSERT INTO `auth_user` (`id`, `password`, `last_login`, `is_superuser`, `username`, `first_name`, `last_name`, `email`, `is_staff`, `is_active`, `date_joined`) VALUES
(7, 'pbkdf2_sha256$216000$7EOARvR5RYrA$qV8ZkzoyqXf51CrKZpHZ8VZMypsea+3eZ1Zx3O6wJxM=', NULL, 1, 'admin', '', '', '', 1, 1, '2022-03-07 13:04:16.014433');

-- --------------------------------------------------------

--
-- Table structure for table `auth_user_groups`
--

CREATE TABLE `auth_user_groups` (
  `id` int NOT NULL,
  `user_id` int NOT NULL,
  `group_id` int NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `auth_user_user_permissions`
--

CREATE TABLE `auth_user_user_permissions` (
  `id` int NOT NULL,
  `user_id` int NOT NULL,
  `permission_id` int NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `axes_accessattempt`
--

CREATE TABLE `axes_accessattempt` (
  `id` int NOT NULL,
  `user_agent` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `ip_address` char(39) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `username` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `http_accept` varchar(1025) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `path_info` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `attempt_time` datetime(6) NOT NULL,
  `get_data` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `post_data` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `failures_since_start` int UNSIGNED NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `axes_accessfailurelog`
--

CREATE TABLE `axes_accessfailurelog` (
  `id` int NOT NULL,
  `user_agent` varchar(255) NOT NULL,
  `ip_address` char(39) DEFAULT NULL,
  `username` varchar(255) DEFAULT NULL,
  `http_accept` varchar(1025) NOT NULL,
  `path_info` varchar(255) NOT NULL,
  `attempt_time` datetime(6) NOT NULL,
  `locked_out` tinyint(1) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- --------------------------------------------------------

--
-- Table structure for table `axes_accesslog`
--

CREATE TABLE `axes_accesslog` (
  `id` int NOT NULL,
  `user_agent` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `ip_address` char(39) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `username` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `http_accept` varchar(1025) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `path_info` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `attempt_time` datetime(6) NOT NULL,
  `logout_time` datetime(6) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `django_admin_log`
--

CREATE TABLE `django_admin_log` (
  `id` int NOT NULL,
  `action_time` datetime(6) NOT NULL,
  `object_id` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
  `object_repr` varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `action_flag` smallint UNSIGNED NOT NULL,
  `change_message` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `content_type_id` int DEFAULT NULL,
  `user_id` int NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `django_content_type`
--

CREATE TABLE `django_content_type` (
  `id` int NOT NULL,
  `app_label` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `model` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `django_content_type`
--

INSERT INTO `django_content_type` (`id`, `app_label`, `model`) VALUES
(23, 'admin', 'logentry'),
(29, 'admin_honeypot', 'loginattempt'),
(25, 'auth', 'group'),
(24, 'auth', 'permission'),
(26, 'auth', 'user'),
(30, 'axes', 'accessattempt'),
(32, 'axes', 'accessfailurelog'),
(31, 'axes', 'accesslog'),
(27, 'contenttypes', 'contenttype'),
(17, 'editor', 'application'),
(18, 'editor', 'project'),
(22, 'editor', 'projectuser'),
(21, 'editor', 'release'),
(19, 'editor', 'specitem'),
(20, 'editor', 'valset'),
(28, 'sessions', 'session');

-- --------------------------------------------------------

--
-- Table structure for table `django_migrations`
--

CREATE TABLE `django_migrations` (
  `id` int NOT NULL,
  `app` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `applied` datetime(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `django_migrations`
--

INSERT INTO `django_migrations` (`id`, `app`, `name`, `applied`) VALUES
(36, 'contenttypes', '0001_initial', '2022-03-07 13:02:58.550719'),
(37, 'auth', '0001_initial', '2022-03-07 13:02:58.562611'),
(38, 'admin', '0001_initial', '2022-03-07 13:02:58.572165'),
(39, 'admin', '0002_logentry_remove_auto_add', '2022-03-07 13:02:58.577837'),
(40, 'admin', '0003_logentry_add_action_flag_choices', '2022-03-07 13:02:58.584583'),
(41, 'admin_honeypot', '0001_initial', '2022-03-07 13:02:58.590277'),
(42, 'admin_honeypot', '0002_auto_20160208_0854', '2022-03-07 13:02:58.600053'),
(43, 'contenttypes', '0002_remove_content_type_name', '2022-03-07 13:02:58.605869'),
(44, 'auth', '0002_alter_permission_name_max_length', '2022-03-07 13:02:58.611266'),
(45, 'auth', '0003_alter_user_email_max_length', '2022-03-07 13:02:58.617772'),
(46, 'auth', '0004_alter_user_username_opts', '2022-03-07 13:02:58.623106'),
(47, 'auth', '0005_alter_user_last_login_null', '2022-03-07 13:02:58.633331'),
(48, 'auth', '0006_require_contenttypes_0002', '2022-03-07 13:02:58.641473'),
(49, 'auth', '0007_alter_validators_add_error_messages', '2022-03-07 13:02:58.646975'),
(50, 'auth', '0008_alter_user_username_max_length', '2022-03-07 13:02:58.653288'),
(51, 'auth', '0009_alter_user_last_name_max_length', '2022-03-07 13:02:58.659748'),
(52, 'auth', '0010_alter_group_name_max_length', '2022-03-07 13:02:58.666184'),
(53, 'auth', '0011_update_proxy_permissions', '2022-03-07 13:02:58.672880'),
(54, 'auth', '0012_alter_user_first_name_max_length', '2022-03-07 13:02:58.682934'),
(55, 'axes', '0001_initial', '2022-03-07 13:02:58.691034'),
(56, 'axes', '0002_auto_20151217_2044', '2022-03-07 13:02:58.701853'),
(57, 'axes', '0003_auto_20160322_0929', '2022-03-07 13:02:58.711454'),
(58, 'axes', '0004_auto_20181024_1538', '2022-03-07 13:02:58.718275'),
(59, 'axes', '0005_remove_accessattempt_trusted', '2022-03-07 13:02:58.723173'),
(60, 'axes', '0006_remove_accesslog_trusted', '2022-03-07 13:02:58.732943'),
(61, 'editor', '0001_initial', '2022-03-07 13:02:58.741356'),
(62, 'editor', '0002_projectuser_role', '2022-03-07 13:02:58.746892'),
(63, 'editor', '0003_specitem_change_log', '2022-03-07 13:02:58.752389'),
(64, 'editor', '0004_specitem_implementation', '2022-03-07 13:02:58.763746'),
(65, 'editor', '0005_auto_20210416_1234', '2022-03-07 13:02:58.773787'),
(66, 'editor', '0006_auto_20210718_1241', '2022-03-07 13:02:58.781090'),
(67, 'editor', '0007_auto_20210721_0648', '2022-03-07 13:02:58.790120'),
(68, 'editor', '0008_auto_20210721_0808', '2022-03-07 13:02:58.799000'),
(69, 'editor', '0009_application_cats', '2022-03-07 13:02:58.804700'),
(70, 'editor', '0010_specitem_s_data', '2022-03-07 13:02:58.811791'),
(71, 'sessions', '0001_initial', '2022-03-07 13:02:58.818454'),
(72, 'axes', '0007_alter_accessattempt_unique_together', '2022-11-28 18:24:33.149483'),
(73, 'axes', '0008_accessfailurelog', '2022-11-28 18:24:33.301041');

-- --------------------------------------------------------

--
-- Table structure for table `django_session`
--

CREATE TABLE `django_session` (
  `session_key` varchar(40) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `session_data` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `expire_date` datetime(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `editor_application`
--

CREATE TABLE `editor_application` (
  `id` int NOT NULL,
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `desc` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  `project_id` int NOT NULL,
  `release_id` int NOT NULL,
  `cats` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `editor_project`
--

CREATE TABLE `editor_project` (
  `id` int NOT NULL,
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `desc` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  `owner_id` int NOT NULL,
  `release_id` int NOT NULL,
  `cats` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `editor_projectuser`
--

CREATE TABLE `editor_projectuser` (
  `id` int NOT NULL,
  `updated_at` date NOT NULL,
  `project_id` int NOT NULL,
  `user_id` int NOT NULL,
  `role` varchar(24) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `editor_release`
--

CREATE TABLE `editor_release` (
  `id` int NOT NULL,
  `desc` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  `project_version` smallint UNSIGNED NOT NULL,
  `application_version` smallint UNSIGNED NOT NULL,
  `previous_id` int DEFAULT NULL,
  `release_author_id` int NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `editor_specitem`
--

CREATE TABLE `editor_specitem` (
  `id` int NOT NULL,
  `cat` varchar(24) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `domain` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `title` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `desc` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  `rationale` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `remarks` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `p_kind` varchar(24) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `s_kind` varchar(24) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `value` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `t1` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `t2` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `t3` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `t4` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `t5` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `n1` int NOT NULL,
  `n2` int NOT NULL,
  `n3` int NOT NULL,
  `application_id` int DEFAULT NULL,
  `owner_id` int NOT NULL,
  `p_link_id` int DEFAULT NULL,
  `previous_id` int DEFAULT NULL,
  `project_id` int NOT NULL,
  `s_link_id` int DEFAULT NULL,
  `val_set_id` int NOT NULL,
  `change_log` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `implementation` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `s_data` json NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Table structure for table `editor_valset`
--

CREATE TABLE `editor_valset` (
  `id` int NOT NULL,
  `updated_at` date NOT NULL,
  `name` varchar(24) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `desc` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `project_id` int NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Indexes for dumped tables
--

--
-- Indexes for table `admin_honeypot_loginattempt`
--
ALTER TABLE `admin_honeypot_loginattempt`
  ADD PRIMARY KEY (`id`);

--
-- Indexes for table `auth_group`
--
ALTER TABLE `auth_group`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `name` (`name`);

--
-- Indexes for table `auth_group_permissions`
--
ALTER TABLE `auth_group_permissions`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `auth_group_permissions_group_id_permission_id_0cd325b0_uniq` (`group_id`,`permission_id`),
  ADD KEY `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` (`permission_id`);

--
-- Indexes for table `auth_permission`
--
ALTER TABLE `auth_permission`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `auth_permission_content_type_id_codename_01ab375a_uniq` (`content_type_id`,`codename`);

--
-- Indexes for table `auth_user`
--
ALTER TABLE `auth_user`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `username` (`username`);

--
-- Indexes for table `auth_user_groups`
--
ALTER TABLE `auth_user_groups`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `auth_user_groups_user_id_group_id_94350c0c_uniq` (`user_id`,`group_id`),
  ADD KEY `auth_user_groups_group_id_97559544_fk_auth_group_id` (`group_id`);

--
-- Indexes for table `auth_user_user_permissions`
--
ALTER TABLE `auth_user_user_permissions`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `auth_user_user_permissions_user_id_permission_id_14a6b632_uniq` (`user_id`,`permission_id`),
  ADD KEY `auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm` (`permission_id`);

--
-- Indexes for table `axes_accessattempt`
--
ALTER TABLE `axes_accessattempt`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `axes_accessattempt_username_ip_address_user_agent_8ea22282_uniq` (`username`,`ip_address`,`user_agent`),
  ADD KEY `axes_accessattempt_ip_address_10922d9c` (`ip_address`),
  ADD KEY `axes_accessattempt_user_agent_ad89678b` (`user_agent`),
  ADD KEY `axes_accessattempt_username_3f2d4ca0` (`username`);

--
-- Indexes for table `axes_accessfailurelog`
--
ALTER TABLE `axes_accessfailurelog`
  ADD PRIMARY KEY (`id`),
  ADD KEY `axes_accessfailurelog_user_agent_ea145dda` (`user_agent`),
  ADD KEY `axes_accessfailurelog_ip_address_2e9f5a7f` (`ip_address`),
  ADD KEY `axes_accessfailurelog_username_a8b7e8a4` (`username`);

--
-- Indexes for table `axes_accesslog`
--
ALTER TABLE `axes_accesslog`
  ADD PRIMARY KEY (`id`),
  ADD KEY `axes_accesslog_ip_address_86b417e5` (`ip_address`),
  ADD KEY `axes_accesslog_user_agent_0e659004` (`user_agent`),
  ADD KEY `axes_accesslog_username_df93064b` (`username`);

--
-- Indexes for table `django_admin_log`
--
ALTER TABLE `django_admin_log`
  ADD PRIMARY KEY (`id`),
  ADD KEY `django_admin_log_content_type_id_c4bce8eb_fk_django_co` (`content_type_id`),
  ADD KEY `django_admin_log_user_id_c564eba6_fk_auth_user_id` (`user_id`);

--
-- Indexes for table `django_content_type`
--
ALTER TABLE `django_content_type`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `django_content_type_app_label_model_76bd3d3b_uniq` (`app_label`,`model`);

--
-- Indexes for table `django_migrations`
--
ALTER TABLE `django_migrations`
  ADD PRIMARY KEY (`id`);

--
-- Indexes for table `django_session`
--
ALTER TABLE `django_session`
  ADD PRIMARY KEY (`session_key`),
  ADD KEY `django_session_expire_date_a5c62663` (`expire_date`);

--
-- Indexes for table `editor_application`
--
ALTER TABLE `editor_application`
  ADD PRIMARY KEY (`id`),
  ADD KEY `editor_application_project_id_3fb17da7_fk_editor_project_id` (`project_id`),
  ADD KEY `editor_application_release_id_279f1760_fk_editor_release_id` (`release_id`);

--
-- Indexes for table `editor_project`
--
ALTER TABLE `editor_project`
  ADD PRIMARY KEY (`id`),
  ADD KEY `editor_project_owner_id_484be1be_fk_auth_user_id` (`owner_id`),
  ADD KEY `editor_project_release_id_5f3ce18d_fk_editor_release_id` (`release_id`);

--
-- Indexes for table `editor_projectuser`
--
ALTER TABLE `editor_projectuser`
  ADD PRIMARY KEY (`id`),
  ADD KEY `editor_projectuser_project_id_315050bc_fk_editor_project_id` (`project_id`),
  ADD KEY `editor_projectuser_user_id_22dae994_fk_auth_user_id` (`user_id`);

--
-- Indexes for table `editor_release`
--
ALTER TABLE `editor_release`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `previous_id` (`previous_id`),
  ADD KEY `editor_release_release_author_id_66a33176_fk_auth_user_id` (`release_author_id`);

--
-- Indexes for table `editor_specitem`
--
ALTER TABLE `editor_specitem`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `previous_id` (`previous_id`),
  ADD KEY `editor_specitem_application_id_99457612_fk_editor_application_id` (`application_id`),
  ADD KEY `editor_specitem_owner_id_94b07f8a_fk_auth_user_id` (`owner_id`),
  ADD KEY `editor_specitem_p_link_id_9567129f_fk_editor_specitem_id` (`p_link_id`),
  ADD KEY `editor_specitem_project_id_310943b0_fk_editor_project_id` (`project_id`),
  ADD KEY `editor_specitem_s_link_id_1161867f_fk_editor_specitem_id` (`s_link_id`),
  ADD KEY `editor_specitem_val_set_id_448f6813_fk_editor_valset_id` (`val_set_id`);

--
-- Indexes for table `editor_valset`
--
ALTER TABLE `editor_valset`
  ADD PRIMARY KEY (`id`),
  ADD KEY `editor_valset_project_id_1c38fc84_fk_editor_project_id` (`project_id`);

--
-- AUTO_INCREMENT for dumped tables
--

--
-- AUTO_INCREMENT for table `admin_honeypot_loginattempt`
--
ALTER TABLE `admin_honeypot_loginattempt`
  MODIFY `id` int NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `auth_group`
--
ALTER TABLE `auth_group`
  MODIFY `id` int NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `auth_group_permissions`
--
ALTER TABLE `auth_group_permissions`
  MODIFY `id` int NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `auth_permission`
--
ALTER TABLE `auth_permission`
  MODIFY `id` int NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=129;

--
-- AUTO_INCREMENT for table `auth_user`
--
ALTER TABLE `auth_user`
  MODIFY `id` int NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=16;

--
-- AUTO_INCREMENT for table `auth_user_groups`
--
ALTER TABLE `auth_user_groups`
  MODIFY `id` int NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `auth_user_user_permissions`
--
ALTER TABLE `auth_user_user_permissions`
  MODIFY `id` int NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `axes_accessattempt`
--
ALTER TABLE `axes_accessattempt`
  MODIFY `id` int NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=17;

--
-- AUTO_INCREMENT for table `axes_accessfailurelog`
--
ALTER TABLE `axes_accessfailurelog`
  MODIFY `id` int NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `axes_accesslog`
--
ALTER TABLE `axes_accesslog`
  MODIFY `id` int NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=376;

--
-- AUTO_INCREMENT for table `django_admin_log`
--
ALTER TABLE `django_admin_log`
  MODIFY `id` int NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=31;

--
-- AUTO_INCREMENT for table `django_content_type`
--
ALTER TABLE `django_content_type`
  MODIFY `id` int NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=33;

--
-- AUTO_INCREMENT for table `django_migrations`
--
ALTER TABLE `django_migrations`
  MODIFY `id` int NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=74;

--
-- AUTO_INCREMENT for table `editor_application`
--
ALTER TABLE `editor_application`
  MODIFY `id` int NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=24;

--
-- AUTO_INCREMENT for table `editor_project`
--
ALTER TABLE `editor_project`
  MODIFY `id` int NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=13;

--
-- AUTO_INCREMENT for table `editor_projectuser`
--
ALTER TABLE `editor_projectuser`
  MODIFY `id` int NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=25;

--
-- AUTO_INCREMENT for table `editor_release`
--
ALTER TABLE `editor_release`
  MODIFY `id` int NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=88;

--
-- AUTO_INCREMENT for table `editor_specitem`
--
ALTER TABLE `editor_specitem`
  MODIFY `id` int NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=6136;

--
-- AUTO_INCREMENT for table `editor_valset`
--
ALTER TABLE `editor_valset`
  MODIFY `id` int NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=14;

--
-- Constraints for dumped tables
--

--
-- Constraints for table `auth_group_permissions`
--
ALTER TABLE `auth_group_permissions`
  ADD CONSTRAINT `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` FOREIGN KEY (`permission_id`) REFERENCES `auth_permission` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  ADD CONSTRAINT `auth_group_permissions_group_id_b120cbf9_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `auth_group` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT;

--
-- Constraints for table `auth_permission`
--
ALTER TABLE `auth_permission`
  ADD CONSTRAINT `auth_permission_content_type_id_2f476e4b_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `django_content_type` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT;

--
-- Constraints for table `auth_user_groups`
--
ALTER TABLE `auth_user_groups`
  ADD CONSTRAINT `auth_user_groups_group_id_97559544_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `auth_group` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  ADD CONSTRAINT `auth_user_groups_user_id_6a12ed8b_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT;

--
-- Constraints for table `auth_user_user_permissions`
--
ALTER TABLE `auth_user_user_permissions`
  ADD CONSTRAINT `auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm` FOREIGN KEY (`permission_id`) REFERENCES `auth_permission` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  ADD CONSTRAINT `auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT;

--
-- Constraints for table `django_admin_log`
--
ALTER TABLE `django_admin_log`
  ADD CONSTRAINT `django_admin_log_content_type_id_c4bce8eb_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `django_content_type` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  ADD CONSTRAINT `django_admin_log_user_id_c564eba6_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT;

--
-- Constraints for table `editor_application`
--
ALTER TABLE `editor_application`
  ADD CONSTRAINT `editor_application_project_id_3fb17da7_fk_editor_project_id` FOREIGN KEY (`project_id`) REFERENCES `editor_project` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  ADD CONSTRAINT `editor_application_release_id_279f1760_fk_editor_release_id` FOREIGN KEY (`release_id`) REFERENCES `editor_release` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT;

--
-- Constraints for table `editor_project`
--
ALTER TABLE `editor_project`
  ADD CONSTRAINT `editor_project_owner_id_484be1be_fk_auth_user_id` FOREIGN KEY (`owner_id`) REFERENCES `auth_user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  ADD CONSTRAINT `editor_project_release_id_5f3ce18d_fk_editor_release_id` FOREIGN KEY (`release_id`) REFERENCES `editor_release` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT;

--
-- Constraints for table `editor_projectuser`
--
ALTER TABLE `editor_projectuser`
  ADD CONSTRAINT `editor_projectuser_project_id_315050bc_fk_editor_project_id` FOREIGN KEY (`project_id`) REFERENCES `editor_project` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  ADD CONSTRAINT `editor_projectuser_user_id_22dae994_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT;

--
-- Constraints for table `editor_release`
--
ALTER TABLE `editor_release`
  ADD CONSTRAINT `editor_release_previous_id_96a0cd1f_fk_editor_release_id` FOREIGN KEY (`previous_id`) REFERENCES `editor_release` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  ADD CONSTRAINT `editor_release_release_author_id_66a33176_fk_auth_user_id` FOREIGN KEY (`release_author_id`) REFERENCES `auth_user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT;

--
-- Constraints for table `editor_specitem`
--
ALTER TABLE `editor_specitem`
  ADD CONSTRAINT `editor_specitem_application_id_99457612_fk_editor_application_id` FOREIGN KEY (`application_id`) REFERENCES `editor_application` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  ADD CONSTRAINT `editor_specitem_owner_id_94b07f8a_fk_auth_user_id` FOREIGN KEY (`owner_id`) REFERENCES `auth_user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  ADD CONSTRAINT `editor_specitem_p_link_id_9567129f_fk_editor_specitem_id` FOREIGN KEY (`p_link_id`) REFERENCES `editor_specitem` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  ADD CONSTRAINT `editor_specitem_previous_id_6550eb12_fk_editor_specitem_id` FOREIGN KEY (`previous_id`) REFERENCES `editor_specitem` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  ADD CONSTRAINT `editor_specitem_project_id_310943b0_fk_editor_project_id` FOREIGN KEY (`project_id`) REFERENCES `editor_project` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  ADD CONSTRAINT `editor_specitem_s_link_id_1161867f_fk_editor_specitem_id` FOREIGN KEY (`s_link_id`) REFERENCES `editor_specitem` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  ADD CONSTRAINT `editor_specitem_val_set_id_448f6813_fk_editor_valset_id` FOREIGN KEY (`val_set_id`) REFERENCES `editor_valset` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT;

--
-- Constraints for table `editor_valset`
--
ALTER TABLE `editor_valset`
  ADD CONSTRAINT `editor_valset_project_id_1c38fc84_fk_editor_project_id` FOREIGN KEY (`project_id`) REFERENCES `editor_project` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT;
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
