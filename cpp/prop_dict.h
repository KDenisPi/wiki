/**
 * @file prop_dict.h
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-08-12
 *
 * @copyright Copyright (c) 2025
 *
 */
#ifndef WIKI_PROPDICT_H_
#define WIKI_PROPDICT_H_


#include <string>
#include <tuple>
#include <vector>
#include <unordered_set>
#include <algorithm>
#include <memory>

#include "rapidjson/document.h"

#include "defines.h"

namespace wiki {

class Properties{
public:
    Properties() {
        ptr_prop = std::make_shared<rapidjson::Document>();
        buffer = std::shared_ptr<char>(new char[MAX_LINE_LENGTH]);
    }

    /**
     * @brief Destroy the Properties object
     *
     */
    virtual ~Properties() {
        if(ptr_prop)
            ptr_prop.reset();
    }

    bool load(const std::string& filename);

    /**
     * @brief Load a selection list from a ';'-delimited file, first field is
     * the ID (Qxxx or Pxxx), anything after it is ignored. Lines starting
     * with '#' and empty lines are skipped, so the files stay commentable.
     *
     * @param filename
     * @param target
     * @return number of IDs loaded, -1 if the file could not be read
     */
    int load_selection(const std::string& filename, std::unordered_set<pID>& target);

    /**
     * @brief Load the list of classes (P31 values) worth selecting.
     * Replaces the built-in list when the file is present.
     *
     * @param filename
     * @return number of classes loaded, -1 on error
     */
    int load_class_selection(const std::string& filename){
        const int res = load_selection(filename, prop_P31);
        if(res > 0){
            std::cout << "Classes (P31) loaded from " << filename << ": " << res << std::endl;
        }
        return res;
    }

    /**
     * @brief Load the list of date properties to extract.
     * Replaces the built-in list when the file is present.
     *
     * @param filename
     * @return number of properties loaded, -1 on error
     */
    int load_property_selection(const std::string& filename){
        const int res = load_selection(filename, prop_important);
        if(res > 0){
            std::cout << "Date properties loaded from " << filename << ": " << res << std::endl;
        }
        return res;
    }

    /**
     * @brief Load the list of attribute properties to extract (occupation,
     * citizenship, place, genre, ...). Replaces the built-in list when the
     * file is present.
     *
     * @param filename
     * @return number of properties loaded, -1 on error
     */
    int load_attribute_selection(const std::string& filename){
        const int res = load_selection(filename, prop_attribute);
        if(res > 0){
            std::cout << "Attribute properties loaded from " << filename << ": " << res << std::endl;
        }
        return res;
    }

    /**
     * @brief
     *
     * @return true
     * @return false
     */
    inline bool is_loaded() const {
        return (ptr_prop ? loaded : false);
    }

    /**
     * @brief
     *
     * @param prop_id
     * @return const p_info&
     */
    const pInfo get_prop(const pID& prop_id) const;

    /**
     * @brief
     *
     * @param v_props
     */
    void load_important_property(const std::vector<pID>& v_props){
        prop_important.insert(v_props.begin(), v_props.end());
    }

    /**
     * @brief
     *
     * @param v_props
     */
    void load_instance_of_property(const std::vector<pID>& v_props){
        prop_P31.insert(v_props.begin(), v_props.end());
    }

    /**
     * @brief
     *
     * @param v_props
     */
    void load_attribute_property(const std::vector<pID>& v_props){
        prop_attribute.insert(v_props.begin(), v_props.end());
    }


    /**
     * @brief
     *
     * @param prop_id
     * @return true
     * @return false
     */
    bool is_important_property(const pID& prop_id) const {
        return (prop_important.find(prop_id) != prop_important.end());
    }

    bool is_useful_instance_of_value(const pID& prop_id) const {
        return (prop_P31.find(prop_id) != prop_P31.end());
    }

    /**
     * @brief Attribute properties carry the non-date dimensions of an item
     * (occupation, citizenship, place, genre) and hold an item ID as a value,
     * not a date.
     *
     * @param prop_id
     * @return true
     * @return false
     */
    bool is_attribute_property(const pID& prop_id) const {
        return (prop_attribute.find(prop_id) != prop_attribute.end());
    }

    /**
     * @brief Number of classes currently used for item selection
     *
     * @return size_t
     */
    size_t class_count() const {
        return prop_P31.size();
    }

    /**
     * @brief Number of attribute properties currently extracted
     *
     * @return size_t
     */
    size_t attribute_count() const {
        return prop_attribute.size();
    }

    /**
     * @brief
     *
     * @return size_t
     */
    size_t MemberCount() const {
        return (is_loaded() ? ptr_prop->MemberCount() : 0);
    }

    /**
     * @brief
     *
     * @return * const std::shared_ptr<rapidjson::Document>
     */
    const std::shared_ptr<rapidjson::Document> get(){
        return ptr_prop;
    }

protected:
    bool loaded = false;
    std::shared_ptr<char> buffer; // Declare a character array (buffer) to store the line

    std::shared_ptr<rapidjson::Document> ptr_prop;

    /*
    Both sets are filled once at start up and are read-only while the parser
    threads run, so concurrent lookups need no locking. They are hash sets and
    not sorted vectors because the class set holds ~300K entries after the
    P279 closure and is probed for every P31 value of every item.
    */
    std::unordered_set<pID> prop_important;
    std::unordered_set<pID> prop_P31;  //Good values for instance of properties
    std::unordered_set<pID> prop_attribute;  //Non-date properties kept for every selected item
};

}//namespace wiki

#endif