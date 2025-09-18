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
#include <map>
#include <vector>
#include <memory>

#include "rapidjson/document.h"

#include "defines.h"

namespace wiki {

using pID = std::string;

/**
 * @brief Property information
 * property ID, label, description
 *
 */
using pInfo = std::tuple<pID, std::string, std::string>;

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
     * @brief
     *
     * @return true
     * @return false
     */
    bool is_loaded() const {
        return (ptr_prop ? loaded : false);
    }

    /**
     * @brief
     *
     * @param prop_id
     * @return const p_info&
     */
    const pInfo get(const pID& prop_id) const;

    /**
     * @brief
     *
     * @param v_props
     */
    void load_important_property(std::vector<pID> v_props){
        const std::string p_unk("Unknown");

        for(auto prop : v_props){
            if(is_loaded()){
                auto [p_id, p_label, p_descr] = get(prop);
                prop_important[prop] = (p_id.empty() ? p_unk : p_label);
            }
            else
                prop_important[prop] = p_unk;
        }
    }

    /**
     * @brief
     *
     * @param prop_id
     * @return true
     * @return false
     */
    bool is_important_property(const pID& prop_id) const {
        return (prop_important.end() != prop_important.find(prop_id));
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
    std::map<pID, std::string> prop_important;
};

}//namespace wiki

#endif